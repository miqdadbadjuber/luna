# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

"""Isolated backend service for Luna Studio (AI Clipper Studio & Full Video Studio).

All edits are stored non-destructively in ``studio_state.json`` inside the
project folder, uploaded music lives in ``studio_assets/``, and rendered
exports are written to ``studio_exports/`` so original media files and
``meta.json`` are never overwritten.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from . import ffmpeg_setup, storage_manager, vault_service

STUDIO_STATE_FILE = "studio_state.json"
STUDIO_ASSETS_DIR = "studio_assets"
STUDIO_EXPORTS_DIR = "studio_exports"
STUDIO_CACHE_DIR = "studio_cache"
ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".webm"}
VIDEO_FILE_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
ALLOWED_CROP_RATIOS = {"original", "16:9", "9:16", "1:1", "3:4"}
ALLOWED_COLOR_PRESETS = {"natural", "warm", "crisp", "bw", "cinematic", "vivid", "custom"}
ALLOWED_CURVE_PRESETS = {"none", "dip", "pulse", "fast_in", "custom"}
MAX_AUDIO_BYTES = 60 * 1024 * 1024  # 60 MB
MAX_VIDEO_EXTRACT_BYTES = 250 * 1024 * 1024  # 250 MB for extracting audio from video files


def _is_video_file_record(f: Any) -> bool:
    if not isinstance(f, dict):
        return False
    ftype = str(f.get("type") or "").strip().lower()
    if ftype == "audio":
        return False
    if ftype == "video":
        return True
    name = str(f.get("filename") or f.get("file_path") or "").strip().lower()
    ext = os.path.splitext(name)[1]
    if ext in ALLOWED_AUDIO_EXTS and ext != ".webm":
        return False
    return ext in VIDEO_FILE_EXTS or not ext


def _is_trimmer_project(proj: Dict[str, Any]) -> bool:
    act = str(proj.get("action") or "").lower()
    cat = str(proj.get("category") or "").lower()
    return act in ("type_yt_clip", "manual_clip") or "trim" in cat


def _is_ai_short_clips_project(proj: Dict[str, Any]) -> bool:
    if not isinstance(proj, dict) or proj.get("virtual"):
        return False
    if _is_trimmer_project(proj):
        return False
    act = str(proj.get("action") or "").lower()
    cat = str(proj.get("category") or "").lower()
    if "ai_clip" in act or "01-ai-clips" in cat:
        return True
    files = proj.get("files") or []
    return any(
        "ai_clip" in str(f.get("action") or "").lower()
        or "01-ai-clips" in str(f.get("category") or "").lower()
        for f in files
        if isinstance(f, dict)
    )


def _is_full_video_project(proj: Dict[str, Any]) -> bool:
    if not isinstance(proj, dict) or proj.get("virtual"):
        return False
    if _is_trimmer_project(proj) or _is_ai_short_clips_project(proj):
        return False
    files = proj.get("files") or []
    return any(_is_video_file_record(f) for f in files)


def get_studio_mode(proj: Dict[str, Any]) -> Optional[str]:
    if _is_ai_short_clips_project(proj):
        return "ai_clip"
    if _is_full_video_project(proj):
        return "full_video"
    return None


def _resolve_project_folder(proj: Dict[str, Any]) -> Optional[str]:
    root = storage_manager.get_storage_root()
    folder = proj.get("folder_path")
    if isinstance(folder, str) and folder and os.path.isdir(folder):
        if vault_service._is_inside_storage(folder, root):
            return os.path.abspath(folder)
    # Fallback: locate folder from first valid clip file inside storage root
    for f in proj.get("files") or []:
        if not isinstance(f, dict):
            continue
        fp = f.get("file_path")
        if isinstance(fp, str) and fp and os.path.isfile(fp):
            parent = os.path.dirname(fp)
            if vault_service._is_inside_storage(parent, root):
                return os.path.abspath(parent)
    return None


def find_studio_project(project_id: str) -> Optional[Tuple[Dict[str, Any], str]]:
    if not project_id or not isinstance(project_id, str):
        return None
    for proj in vault_service.list_vault_projects():
        if proj.get("project_id") != project_id:
            continue
        if not get_studio_mode(proj):
            return None
        folder = _resolve_project_folder(proj)
        if not folder:
            return None
        return proj, folder
    return None


def _resolve_clip_path(file_rec: Dict[str, Any], folder: str) -> Optional[str]:
    root = storage_manager.get_storage_root()
    fp = file_rec.get("file_path")
    if isinstance(fp, str) and fp and os.path.isfile(fp) and vault_service._is_inside_storage(fp, root):
        return os.path.abspath(fp)
    fname = file_rec.get("filename")
    if isinstance(fname, str) and fname.strip():
        cand = os.path.join(folder, os.path.basename(fname.strip()))
        if os.path.isfile(cand) and vault_service._is_inside_storage(cand, root):
            return os.path.abspath(cand)
    return None


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        num = float(val)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(round(float(val)))
    except (TypeError, ValueError):
        return default


def _media_vault_url(abs_path: str) -> str:
    root = os.path.abspath(storage_manager.get_storage_root())
    try:
        rel = os.path.relpath(os.path.abspath(abs_path), root).replace("\\", "/")
        return f"/media-vault/{quote(rel, safe='/')}"
    except ValueError:
        return ""


def _probe_video_info(video_path: str) -> Tuple[float, int, int]:
    """Return display (duration_sec, width, height) using ffprobe (honoring rotation metadata)."""
    dur, width, height = 0.0, 1080, 1920
    if not ffmpeg_setup.ensure_ffmpeg():
        return dur, width, height
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:stream_tags=rotate:stream_side_data=rotation:format=duration",
            "-of",
            "json",
            video_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            fmt_dur = data.get("format", {}).get("duration")
            if fmt_dur is not None:
                dur = max(0.0, float(fmt_dur))
            streams = data.get("streams") or []
            if streams:
                st0 = streams[0]
                width = int(st0.get("width") or width)
                height = int(st0.get("height") or height)
                rot = 0
                for sd in st0.get("side_data_list") or []:
                    if isinstance(sd, dict) and sd.get("rotation") is not None:
                        try:
                            rot = int(round(float(sd["rotation"])))
                            break
                        except (TypeError, ValueError):
                            pass
                if rot == 0:
                    tag_rot = (st0.get("tags") or {}).get("rotate")
                    if tag_rot is not None:
                        try:
                            rot = int(round(float(tag_rot)))
                        except (TypeError, ValueError):
                            rot = 0
                if abs(rot) % 180 == 90:
                    width, height = height, width
    except Exception:
        pass
    return dur, width, height


def _probe_has_video(media_path: str) -> bool:
    """Return True if media_path contains at least one real video stream (ignoring attached cover art)."""
    if not media_path or not os.path.isfile(media_path) or not ffmpeg_setup.ensure_ffmpeg():
        return False
    try:
        res = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v",
                "-show_entries",
                "stream=codec_type,disposition",
                "-of",
                "json",
                media_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            for st in data.get("streams") or []:
                disp = st.get("disposition") or {}
                if not disp.get("attached_pic"):
                    return True
    except Exception:
        pass
    return False


def _probe_audio_duration(audio_path: str) -> float:
    """Return audio duration in seconds using ffprobe, or 0.0 if unavailable."""
    if not audio_path or not os.path.isfile(audio_path) or not ffmpeg_setup.ensure_ffmpeg():
        return 0.0
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=duration",
            "-of",
            "json",
            audio_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            fmt_dur = data.get("format", {}).get("duration")
            if fmt_dur is not None:
                val = float(fmt_dur)
                if val > 0.05:
                    return round(val, 3)
            for st in data.get("streams") or []:
                sdur = st.get("duration")
                if sdur is not None:
                    val = float(sdur)
                    if val > 0.05:
                        return round(val, 3)
    except Exception:
        pass
    return 0.0


def _resolve_music_slice_start(music_path: str, slice_start: float, target_dur: float) -> float:
    """Only honor a non-zero sliceStart when the music track is actually longer than the target video."""
    req_start = max(0.0, float(slice_start or 0.0))
    music_dur = _probe_audio_duration(music_path)
    if music_dur <= 0.05:
        return req_start
    if music_dur <= max(0.1, float(target_dur or 0.0)) + 0.5:
        return 0.0
    return min(req_start, max(0.0, music_dur - float(target_dur)))


_SRT_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _srt_ts(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000.0


def _parse_srt_file(srt_path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(srt_path):
        return []
    try:
        with open(srt_path, "r", encoding="utf-8-sig", errors="replace") as f:
            raw = f.read()
    except OSError:
        return []

    cues: List[Dict[str, Any]] = []
    blocks = re.split(r"\r?\n\s*\r?\n", raw.strip())
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        match = None
        time_line_idx = -1
        for i, ln in enumerate(lines):
            m = _SRT_TIME_RE.search(ln)
            if m:
                match = m
                time_line_idx = i
                break
        if not match:
            continue
        start = _srt_ts(*match.groups()[:4])
        end = _srt_ts(*match.groups()[4:])
        text = " ".join(lines[time_line_idx + 1 :]).strip()
        if text and end > start:
            cues.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return cues


def _read_studio_state(folder: str) -> Dict[str, Any]:
    path = os.path.join(folder, STUDIO_STATE_FILE)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_YT_ID_RE = re.compile(r"(?:youtu\.be/|v=|/shorts/|/embed/)([A-Za-z0-9_-]{11})")

_TAG_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "your", "have", "will",
    "into", "about", "using", "make", "every", "single", "real", "ways", "based",
    "just", "more", "most", "very", "what", "when", "where", "which", "while",
    "how", "why", "who", "can", "could", "would", "should", "really", "actually",
    "one", "two", "three", "four", "five", "ten", "get", "use", "used", "need",
    "they", "them", "their", "there", "these", "those", "only", "also", "been",
    "being", "some", "such", "than", "then", "here", "over", "after", "before",
    "helps", "help", "saves", "save", "once", "best", "good", "like", "literally",
    "simple", "yang", "dan", "atau", "dari", "untuk", "dengan", "pada", "ini",
    "itu", "juga", "cuma", "bisa", "akan", "jadi", "karena", "kalau", "kalo",
    "buat", "pakai", "cara", "bikin", "orang", "banyak", "semua", "tidak",
    "enggak", "gak", "kamu", "anda", "kita", "saya", "mereka", "dalam", "sebagai",
}


def _extract_youtube_id(url: str) -> Optional[str]:
    m = _YT_ID_RE.search(str(url or ""))
    return m.group(1) if m else None


def _generate_adaptive_hashtags(title: str, caption: str) -> str:
    """Derive 1-3 natural topic hashtags from clip title and caption (never hardcoded #luna)."""
    raw = f"{title or ''} {caption or ''}"
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]{1,20}", raw)
    tags: List[str] = []
    seen = set()
    for tok in tokens:
        low = tok.lower()
        if low in _TAG_STOPWORDS or low in seen:
            continue
        if len(low) < 3 and low != "ai":
            continue
        seen.add(low)
        tags.append(f"#{low}")
        if len(tags) >= 3:
            break
    return " ".join(tags)


def _find_project_source_srt(proj: Dict[str, Any], folder: str) -> Optional[str]:
    """Locate a project-level transcript .srt (in project folder or Luna's output cache)."""
    # 1. Transcript saved directly inside the Vault project folder
    direct = os.path.join(folder, "transcript.srt")
    if os.path.isfile(direct):
        return direct
    try:
        for fn in os.listdir(folder):
            if fn.lower().endswith(".srt"):
                cand = os.path.join(folder, fn)
                if os.path.isfile(cand):
                    return cand
    except OSError:
        pass

    # 2. Fallback to Luna's output/ transcript cache keyed by YouTube video ID
    vid = _extract_youtube_id(str(proj.get("source_url") or ""))
    if not vid:
        return None
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "output")
    if not os.path.isdir(output_dir):
        return None
    try:
        matches = [
            os.path.join(output_dir, fn)
            for fn in os.listdir(output_dir)
            if vid in fn and fn.lower().endswith(".srt") and os.path.isfile(os.path.join(output_dir, fn))
        ]
        if matches:
            matches.sort(key=os.path.getmtime, reverse=True)
            return matches[0]
    except OSError:
        pass
    return None


def _find_project_source_words(proj: Dict[str, Any], folder: str) -> List[Dict[str, Any]]:
    """Locate word-level transcript JSON (in project folder or Luna's output cache)."""
    candidates: List[str] = []
    direct = os.path.join(folder, "transcript.words.json")
    if os.path.isfile(direct):
        candidates.append(direct)
    try:
        for fn in os.listdir(folder):
            if fn.lower().endswith(".words.json"):
                cand = os.path.join(folder, fn)
                if os.path.isfile(cand) and cand not in candidates:
                    candidates.append(cand)
    except OSError:
        pass

    if not candidates:
        vid = _extract_youtube_id(str(proj.get("source_url") or ""))
        if vid:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            output_dir = os.path.join(base_dir, "output")
            if os.path.isdir(output_dir):
                try:
                    matches = [
                        os.path.join(output_dir, fn)
                        for fn in os.listdir(output_dir)
                        if vid in fn and fn.lower().endswith(".words.json") and os.path.isfile(os.path.join(output_dir, fn))
                    ]
                    if matches:
                        matches.sort(key=os.path.getmtime, reverse=True)
                        candidates.append(matches[0])
                except OSError:
                    pass

    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            raw_words = payload.get("words") if isinstance(payload, dict) else payload
            if not isinstance(raw_words, list):
                continue
            cleaned: List[Dict[str, Any]] = []
            for item in raw_words:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or item.get("word") or "").strip()
                if not text:
                    continue
                ws = _safe_float(item.get("start"), -1.0)
                we = _safe_float(item.get("end"), ws)
                if ws < 0.0:
                    continue
                cleaned.append({"start": round(ws, 3), "end": round(max(ws, we), 3), "text": text})
            if cleaned:
                cleaned.sort(key=lambda w: (w["start"], w["end"]))
                return cleaned
        except Exception:
            continue
    return []


_WORD_CUE_SENTENCE_END = (".", "?", "!", "…", "。", "？", "！")
_WORD_CUE_CLAUSE_END = (",", ";", ":")


def _build_word_synced_cues(
    words: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    *,
    max_words: int = 7,
    max_chars: int = 42,
    max_dur: float = 2.6,
    pause_split: float = 0.40,
) -> List[Dict[str, Any]]:
    """Group word timestamps into tightly synced Studio cues with exact 2-line splitTime."""
    if not words or clip_end <= clip_start:
        return []
    span = clip_end - clip_start
    rel_words: List[Dict[str, Any]] = []
    for w in words:
        ws = float(w.get("start", 0.0))
        we = float(w.get("end", ws))
        text = str(w.get("text") or "").strip()
        if not text:
            continue
        mid = 0.5 * (ws + we)
        if we <= clip_start + 0.04 or ws >= clip_end - 0.02:
            continue
        if mid < clip_start - 0.06 or mid > clip_end + 0.06:
            continue
        rs = max(0.0, ws - clip_start)
        re_t = min(span, max(rs + 0.04, we - clip_start))
        rel_words.append({"start": round(rs, 3), "end": round(re_t, 3), "text": text})

    if not rel_words:
        return []

    cues: List[Dict[str, Any]] = []
    group: List[Dict[str, Any]] = []

    def flush() -> None:
        nonlocal group
        if not group:
            return
        text = " ".join(item["text"] for item in group).strip()
        if not text:
            group = []
            return
        cue_start = group[0]["start"]
        cue_end = max(cue_start + 0.12, group[-1]["end"])
        cue_obj: Dict[str, Any] = {
            "start": round(cue_start, 3),
            "end": round(min(span, cue_end), 3),
            "text": text,
        }
        lines = _split_two_balanced_lines(text)
        if len(lines) == 2:
            line1_words = len(lines[0].split())
            if 0 < line1_words < len(group):
                raw_split = group[line1_words]["start"]
                if cue_start + 0.04 < raw_split < cue_obj["end"] - 0.04:
                    cue_obj["splitTime"] = round(raw_split, 3)
        cues.append(cue_obj)
        group = []

    for w in rel_words:
        if group:
            prev = group[-1]
            gap = w["start"] - prev["end"]
            cand_text = " ".join(item["text"] for item in group) + " " + w["text"]
            cand_dur = w["end"] - group[0]["start"]
            if (
                gap >= pause_split
                or len(group) >= max_words
                or len(cand_text) > max_chars
                or cand_dur > max_dur
            ):
                flush()
        group.append(w)
        cur_text = " ".join(item["text"] for item in group)
        if w["text"].rstrip().endswith(_WORD_CUE_SENTENCE_END):
            flush()
        elif w["text"].rstrip().endswith(_WORD_CUE_CLAUSE_END) and (len(group) >= 4 or len(cur_text) >= 22):
            flush()
    flush()

    # Keep cues strictly non-overlapping
    for i in range(len(cues) - 1):
        if cues[i]["end"] > cues[i + 1]["start"]:
            cues[i]["end"] = round(max(cues[i]["start"] + 0.08, cues[i + 1]["start"]), 3)
            if "splitTime" in cues[i] and cues[i]["splitTime"] >= cues[i]["end"] - 0.03:
                cues[i].pop("splitTime", None)
    return cues


def _slice_cues_for_clip(
    full_cues: List[Dict[str, Any]], clip_start: float, clip_end: float
) -> List[Dict[str, Any]]:
    if not full_cues or clip_end <= clip_start:
        return []
    sliced: List[Dict[str, Any]] = []
    span = clip_end - clip_start
    for q in full_cues:
        qs = float(q.get("start", 0.0))
        qe = float(q.get("end", 0.0))
        if qe <= clip_start or qs >= clip_end:
            continue
        rel_s = max(0.0, qs - clip_start)
        rel_e = min(span, qe - clip_start)
        if rel_e - rel_s < 0.08:
            continue
        sliced.append({"start": round(rel_s, 3), "end": round(rel_e, 3), "text": str(q.get("text") or "").strip()})
    return sliced


def _sanitize_color(raw: Any) -> Dict[str, Any]:
    default_col = {
        "preset": "natural",
        "brightness": 0,
        "contrast": 0,
        "saturation": 0,
        "exposure": 0,
        "warmth": 0,
        "sharpness": 0,
        "vignette": 0,
    }
    if not isinstance(raw, dict):
        return default_col
    preset = str(raw.get("preset") or "natural").strip().lower()
    if preset not in ALLOWED_COLOR_PRESETS:
        preset = "natural"
    return {
        "preset": preset,
        "brightness": max(-50, min(50, int(round(float(raw.get("brightness") or 0))))),
        "contrast": max(-50, min(50, int(round(float(raw.get("contrast") or 0))))),
        "saturation": max(-50, min(50, int(round(float(raw.get("saturation") or 0))))),
        "exposure": max(-50, min(50, int(round(float(raw.get("exposure") or 0))))),
        "warmth": max(-50, min(50, int(round(float(raw.get("warmth") or 0))))),
        "sharpness": max(0, min(50, int(round(float(raw.get("sharpness") or 0))))),
        "vignette": max(0, min(50, int(round(float(raw.get("vignette") or 0))))),
    }


def _sanitize_curve_points(raw: Any) -> List[float]:
    if not isinstance(raw, list) or len(raw) != 5:
        return [1.0, 1.0, 1.0, 1.0, 1.0]
    out: List[float] = []
    for item in raw:
        try:
            v = round(max(0.25, min(4.0, float(item))), 2)
        except (TypeError, ValueError):
            v = 1.0
        out.append(v)
    return out


def _sanitize_curve_positions(raw: Any) -> List[float]:
    default_pos = [0.0, 0.25, 0.5, 0.75, 1.0]
    if not isinstance(raw, list) or len(raw) != 5:
        return default_pos
    vals: List[float] = []
    for idx, item in enumerate(raw):
        try:
            v = max(0.0, min(1.0, float(item)))
        except (TypeError, ValueError):
            v = default_pos[idx]
        vals.append(v)
    vals[0] = 0.0
    vals[4] = 1.0
    for i in range(1, 4):
        lo = vals[i - 1] + 0.04
        hi = 1.0 - (4 - i) * 0.04
        vals[i] = round(max(lo, min(hi, vals[i])), 4)
    return vals


def _sanitize_segments(raw: Any, dur: float, fallback_start: float = 0.0, fallback_end: float = 0.0) -> List[Dict[str, Any]]:
    max_t = max(0.5, float(dur or 0.0))
    fb_s = max(0.0, min(max_t - 0.25, float(fallback_start or 0.0)))
    fb_e = float(fallback_end or max_t)
    fb_e = min(max_t, max(fb_s + 0.25, fb_e))
    default_seg = [
        {
            "id": "seg_1",
            "sourceStart": round(fb_s, 3),
            "sourceEnd": round(fb_e, 3),
            "volume": 100,
            "speedMode": "normal",
            "speed": 1.0,
            "curvePreset": "none",
            "curvePoints": [1.0, 1.0, 1.0, 1.0, 1.0],
            "curvePositions": [0.0, 0.25, 0.5, 0.75, 1.0],
            "cropX": 50.0,
            "cropY": 50.0,
        }
    ]
    if not isinstance(raw, list) or not raw:
        return default_seg

    cleaned: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw[:40]):
        if not isinstance(item, dict):
            continue
        try:
            ss = max(0.0, min(max_t, float(item.get("sourceStart", 0.0))))
            se = max(0.0, min(max_t, float(item.get("sourceEnd", max_t))))
            vol = max(0, min(100, int(round(float(item.get("volume", 100))))))
            spd = round(max(0.25, min(4.0, float(item.get("speed", 1.0)))), 2)
            crop_x = round(max(0.0, min(100.0, float(item.get("cropX", 50.0)))), 1)
            crop_y = round(max(0.0, min(100.0, float(item.get("cropY", 50.0)))), 1)
        except (TypeError, ValueError):
            continue
        if se - ss < 0.2:
            continue
        smode = "curve" if str(item.get("speedMode") or "").lower() == "curve" else "normal"
        cpreset = str(item.get("curvePreset") or "none").strip().lower()
        if cpreset not in ALLOWED_CURVE_PRESETS:
            cpreset = "none"
        cpts = _sanitize_curve_points(item.get("curvePoints"))
        cpos = _sanitize_curve_positions(item.get("curvePositions"))
        cleaned.append(
            {
                "id": str(item.get("id") or f"seg_{idx + 1}"),
                "sourceStart": round(ss, 3),
                "sourceEnd": round(se, 3),
                "volume": vol,
                "speedMode": smode,
                "speed": spd,
                "curvePreset": cpreset,
                "curvePoints": cpts,
                "curvePositions": cpos,
                "cropX": crop_x,
                "cropY": crop_y,
            }
        )
    return cleaned or default_seg


def _sanitize_crop_ratio(raw: Any) -> str:
    val = str(raw or "original").strip().lower()
    return val if val in ALLOWED_CROP_RATIOS else "original"


def _sanitize_fade(raw: Any) -> float:
    try:
        val = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if val >= 0.9:
        return 1.0
    if val >= 0.35:
        return 0.5
    return 0.0


def _sanitize_audio_keyframes(raw: Any, max_span: float) -> List[Dict[str, float]]:
    """Sanitize sorted per-clip volume keyframes [{t, vol}] relative to clip start."""
    if not isinstance(raw, list) or not raw:
        return []
    span = max(0.1, float(max_span or 0.1))
    pts: List[Tuple[float, float]] = []
    for item in raw[:32]:
        if not isinstance(item, dict):
            continue
        try:
            t = max(0.0, min(span, float(item.get("t", 0.0))))
            vol = max(0.0, min(100.0, float(item.get("vol", 35.0))))
        except (TypeError, ValueError):
            continue
        pts.append((round(t, 3), round(vol, 1)))
    if not pts:
        return []
    pts.sort(key=lambda x: x[0])
    dedup: List[Dict[str, float]] = []
    for t, vol in pts:
        if dedup and abs(t - dedup[-1]["t"]) < 0.02:
            dedup[-1] = {"t": t, "vol": vol}
        else:
            dedup.append({"t": t, "vol": vol})
    return dedup


def _sanitize_audio_clips(
    raw: Any,
    project_id: str,
    assets_dir: str,
    max_timeline_dur: float,
    legacy_music: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Sanitize Full Video multi-block audioClips (auto-migrating legacy clip.music if needed)."""
    dur_cache: Dict[str, float] = {}

    def _get_dur(path: str, fallback: float) -> float:
        if path not in dur_cache:
            probed = _probe_audio_duration(path)
            dur_cache[path] = probed if probed > 0.05 else max(0.0, fallback)
        return dur_cache[path]

    source_list: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        source_list = [x for x in raw[:30] if isinstance(x, dict)]
    elif raw is None and isinstance(legacy_music, dict) and legacy_music.get("assetName"):
        asset_base = os.path.basename(str(legacy_music["assetName"]))
        asset_full = os.path.join(assets_dir, asset_base)
        if os.path.isfile(asset_full):
            sdur = _get_dur(asset_full, float(legacy_music.get("totalDur") or 0.0))
            if sdur > 0.15:
                if max_timeline_dur > 0.2 and sdur <= max_timeline_dur + 0.5:
                    sl_start = 0.0
                else:
                    sl_start = max(0.0, min(max(0.0, sdur - 0.2), float(legacy_music.get("sliceStart") or 0.0)))
                span = min(sdur - sl_start, max_timeline_dur) if max_timeline_dur > 0.2 else (sdur - sl_start)
                if span >= 0.14:
                    source_list = [
                        {
                            "id": "aud_1",
                            "name": str(legacy_music.get("name") or asset_base),
                            "assetName": asset_base,
                            "sourceDur": sdur,
                            "timelineStart": 0.0,
                            "trimStart": sl_start,
                            "trimEnd": sl_start + span,
                            "volume": legacy_music.get("volume", 35),
                            "fadeIn": 0.0,
                            "fadeOut": 0.0,
                            "keyframes": [],
                            "peaks": legacy_music.get("peaks") if isinstance(legacy_music.get("peaks"), list) else [],
                        }
                    ]

    cleaned: List[Dict[str, Any]] = []
    for idx, item in enumerate(source_list):
        raw_asset = item.get("assetName")
        if not raw_asset:
            continue
        asset_base = os.path.basename(str(raw_asset))
        asset_full = os.path.join(assets_dir, asset_base)
        if not os.path.isfile(asset_full):
            continue
        try:
            fb_dur = float(item.get("sourceDur") or item.get("totalDur") or 0.0)
            source_dur = _get_dur(asset_full, fb_dur)
            if source_dur < 0.15:
                continue
            trim_start = max(0.0, min(source_dur - 0.15, float(item.get("trimStart", 0.0))))
            raw_trim_end = item.get("trimEnd")
            trim_end = source_dur if raw_trim_end is None else float(raw_trim_end)
            trim_end = min(source_dur, max(trim_start + 0.15, trim_end))
            tl_start = max(0.0, float(item.get("timelineStart", 0.0)))
            if max_timeline_dur > 0.2:
                if tl_start >= max_timeline_dur - 0.1:
                    continue
                max_avail = max_timeline_dur - tl_start
                if (trim_end - trim_start) > max_avail:
                    trim_end = trim_start + max_avail
            span = trim_end - trim_start
            if span < 0.15:
                continue
            vol = max(0, min(100, int(round(float(item.get("volume", 35))))))
            track_idx = max(0, min(7, int(item.get("track") or 0)))
            max_fade = round(span / 2.0, 3)
            fade_in = round(max(0.0, min(max_fade, float(item.get("fadeIn", 0.0)))), 2)
            fade_out = round(max(0.0, min(max_fade, float(item.get("fadeOut", 0.0)))), 2)
            kfs = _sanitize_audio_keyframes(item.get("keyframes"), span)
            raw_peaks = item.get("peaks")
            peaks: List[float] = []
            if isinstance(raw_peaks, list):
                for x in raw_peaks[:256]:
                    try:
                        fx = float(x)
                        if math.isfinite(fx):
                            peaks.append(round(fx, 4))
                    except (TypeError, ValueError):
                        continue
        except (TypeError, ValueError):
            continue

        cleaned.append(
            {
                "id": str(item.get("id") or f"aud_{idx + 1}"),
                "name": str(item.get("name") or asset_base),
                "assetName": asset_base,
                "url": f"/api/studio/{project_id}/music/{asset_base}",
                "track": track_idx,
                "sourceDur": round(source_dur, 3),
                "timelineStart": round(tl_start, 3),
                "trimStart": round(trim_start, 3),
                "trimEnd": round(trim_end, 3),
                "volume": vol,
                "fadeIn": fade_in,
                "fadeOut": fade_out,
                "keyframes": kfs,
                "peaks": peaks,
            }
        )

    cleaned.sort(key=lambda c: (c["track"], c["timelineStart"]))
    return cleaned


def _build_audio_volume_filter(base_vol_pct: float, keyframes: List[Dict[str, float]]) -> str:
    """Build FFmpeg volume filter (static or piecewise-linear keyframe expression)."""
    base_v = max(0.0, min(1.0, float(base_vol_pct) / 100.0))
    if not keyframes:
        return f"volume={base_v:.4f}"
    if len(keyframes) == 1:
        v0 = max(0.0, min(1.0, float(keyframes[0]["vol"]) / 100.0))
        return f"volume={v0:.4f}"

    expr = f"{max(0.0, min(1.0, float(keyframes[-1]['vol']) / 100.0)):.4f}"
    for i in range(len(keyframes) - 2, -1, -1):
        t0 = float(keyframes[i]["t"])
        t1 = float(keyframes[i + 1]["t"])
        v0 = max(0.0, min(1.0, float(keyframes[i]["vol"]) / 100.0))
        v1 = max(0.0, min(1.0, float(keyframes[i + 1]["vol"]) / 100.0))
        dt = max(0.001, t1 - t0)
        if abs(v1 - v0) < 0.0005:
            seg_expr = f"{v0:.4f}"
        else:
            dv = v1 - v0
            seg_expr = f"({v0:.4f}+({dv:.4f})*(t-{t0:.3f})/{dt:.3f})"
        expr = f"if(lte(t,{t1:.3f}),{seg_expr},{expr})"

    t_first = float(keyframes[0]["t"])
    v_first = max(0.0, min(1.0, float(keyframes[0]["vol"]) / 100.0))
    if t_first > 0.005:
        expr = f"if(lte(t,{t_first:.3f}),{v_first:.4f},{expr})"
    return f"volume=volume='{expr}':eval=frame"


def _sanitize_audio_enhance(raw: Any) -> Dict[str, bool]:
    """Sanitize Smart Audio toggles (Normalize -14 LUFS, Denoise, Auto-Duck BGM)."""
    if not isinstance(raw, dict):
        return {"normalize": False, "denoise": False, "autoDuck": False}
    return {
        "normalize": bool(raw.get("normalize", False)),
        "denoise": bool(raw.get("denoise", False)),
        "autoDuck": bool(raw.get("autoDuck", False)),
    }


def _build_voice_enhance_filters(audio_enhance: Dict[str, bool]) -> List[str]:
    """Return FFmpeg audio filters for original speech track (denoise + broadcast -14 LUFS loudness)."""
    filters: List[str] = []
    if audio_enhance.get("denoise"):
        filters.append("highpass=f=80")
        filters.append("afftdn=nf=-25")
    if audio_enhance.get("normalize"):
        filters.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    return filters


def _compute_audio_peaks_ffmpeg(audio_path: str, bars: int = 160) -> List[float]:
    """Fast server-side waveform peak extraction via FFmpeg PCM pipe (avoids heavy browser RAM decode)."""
    if not audio_path or not os.path.isfile(audio_path) or not ffmpeg_setup.ensure_ffmpeg():
        return []
    n_bars = max(32, min(256, int(bars)))
    try:
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            audio_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "2000",
            "-f",
            "s16le",
            "pipe:1",
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        raw = res.stdout or b""
        if res.returncode != 0 or len(raw) < 4:
            return []
        total_samples = len(raw) // 2
        if total_samples < 1:
            return []
        samples = struct.unpack(f"<{total_samples}h", raw[: total_samples * 2])
        step = max(1, total_samples // n_bars)
        peaks: List[float] = []
        max_val = 1.0
        for i in range(n_bars):
            start = i * step
            end = total_samples if i == n_bars - 1 else min(total_samples, start + step)
            if start >= total_samples:
                peaks.append(0.05)
                continue
            chunk = samples[start:end]
            peak = max((abs(s) for s in chunk), default=0) / 32768.0
            if peak > max_val:
                max_val = peak
            peaks.append(peak)
        # Normalize visually against clip's own peak so quiet tracks remain readable
        norm = max(0.08, max(peaks) if peaks else 1.0)
        return [round(max(0.05, min(1.0, p / norm)), 4) for p in peaks]
    except Exception:
        return []


def _build_audio_clips_mix(
    project_id: str,
    audio_clips: List[Dict[str, Any]],
    base_input_idx: int,
    out_dur: float,
    a_cur: Optional[str],
    af_fade: str = "",
    auto_duck: bool = False,
) -> Tuple[List[str], List[str], Optional[str]]:
    """Build FFmpeg inputs and filter_complex chains for positioned/faded/keyframed audioClips (with optional Auto-Duck)."""
    extra_inputs: List[str] = []
    fc_parts: List[str] = []
    ma_labels: List[str] = []
    inp_idx = base_input_idx

    for j, ac in enumerate(audio_clips):
        asset_path = get_studio_music_path(project_id, str(ac.get("assetName") or ""))
        if not asset_path:
            continue
        ts = max(0.0, float(ac["trimStart"]))
        te = max(ts + 0.15, float(ac["trimEnd"]))
        span = te - ts
        # Fast input-level seek avoids decoding unused leading/trailing audio from 00:00
        extra_inputs += ["-ss", f"{ts:.3f}", "-t", f"{span:.3f}", "-i", asset_path]
        chain = [
            "asetpts=PTS-STARTPTS",
            "aformat=sample_rates=48000:channel_layouts=stereo",
            _build_audio_volume_filter(ac.get("volume", 35), ac.get("keyframes") or []),
        ]
        fade_in = float(ac.get("fadeIn") or 0.0)
        fade_out = float(ac.get("fadeOut") or 0.0)
        if fade_in > 0.02:
            chain.append(f"afade=t=in:st=0:d={min(fade_in, span / 2.0):.3f}")
        if fade_out > 0.02:
            fo_d = min(fade_out, span / 2.0)
            chain.append(f"afade=t=out:st={max(0.0, span - fo_d):.3f}:d={fo_d:.3f}")
        delay_ms = int(round(max(0.0, float(ac.get("timelineStart") or 0.0)) * 1000.0))
        if delay_ms > 0:
            chain.append(f"adelay={delay_ms}:all=1")
        label = f"[ma{j}]"
        fc_parts.append(f"[{inp_idx}:a]{','.join(chain)}{label}")
        ma_labels.append(label)
        inp_idx += 1

    if not ma_labels:
        return [], [], a_cur

    if a_cur:
        fc_parts.append(f"{a_cur}aformat=sample_rates=48000:channel_layouts=stereo[abase]")
    else:
        fc_parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{max(0.2, out_dur):.3f},asetpts=PTS-STARTPTS[abase]")

    if auto_duck and a_cur:
        if len(ma_labels) == 1:
            music_bus = ma_labels[0]
        else:
            fc_parts.append(
                f"{''.join(ma_labels)}amix=inputs={len(ma_labels)}:duration=longest:dropout_transition=0:normalize=0[mraw]"
            )
            music_bus = "[mraw]"
        fc_parts.append("[abase]asplit=2[avoice][asc]")
        fc_parts.append(
            f"{music_bus}[asc]sidechaincompress=threshold=0.025:ratio=6:attack=40:release=350:makeup=1[mduck]"
        )
        fc_parts.append(
            f"[avoice][mduck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0{af_fade}[aout]"
        )
        return extra_inputs, fc_parts, "[aout]"

    mix_inputs = ["[abase]"] + ma_labels
    fc_parts.append(
        f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0:normalize=0{af_fade}[aout]"
    )
    return extra_inputs, fc_parts, "[aout]"


def load_studio_project(project_id: str) -> Optional[Dict[str, Any]]:
    found = find_studio_project(project_id)
    if not found:
        return None
    proj, folder = found
    mode = get_studio_mode(proj) or "ai_clip"
    saved = _read_studio_state(folder)
    saved_clips = {
        c.get("id"): c for c in (saved.get("clips") or []) if isinstance(c, dict) and c.get("id")
    }

    source_srt_path = _find_project_source_srt(proj, folder) if mode == "ai_clip" else None
    source_cues = _parse_srt_file(source_srt_path) if source_srt_path else []
    source_words = _find_project_source_words(proj, folder) if mode == "ai_clip" else []

    assets_dir = os.path.join(folder, STUDIO_ASSETS_DIR)
    clips: List[Dict[str, Any]] = []
    video_files = [
        f
        for f in (proj.get("files") or [])
        if _is_video_file_record(f)
    ]

    for idx, f in enumerate(video_files):
        clip_path = _resolve_clip_path(f, folder)
        if not clip_path:
            continue
        clip_id = str(f.get("id") or f"clip_{idx + 1}")
        sc = saved_clips.get(clip_id, {})

        dur = float(sc.get("dur") or 0.0)
        if dur <= 0.1:
            probed_dur, _, _ = _probe_video_info(clip_path)
            dur = probed_dur
        src_st = float(f.get("start_time") or 0.0)
        src_en = float(f.get("end_time") or 0.0)
        if dur <= 0.1:
            dur = max(1.0, src_en - src_st) if src_en > src_st else 30.0

        cues: List[Dict[str, Any]] = []
        if mode == "ai_clip":
            stem = os.path.splitext(clip_path)[0]
            default_cues = _parse_srt_file(f"{stem}.srt")
            if not default_cues and source_words and src_en > src_st:
                default_cues = _build_word_synced_cues(source_words, src_st, src_en)
            if not default_cues and source_cues and src_en > src_st:
                default_cues = _slice_cues_for_clip(source_cues, src_st, src_en)
            saved_clip_cues = sc.get("cues") if isinstance(sc.get("cues"), list) else None
            cues = saved_clip_cues if (saved_clip_cues and len(saved_clip_cues) > 0) else default_cues

        start = max(0.0, float(sc.get("start", 0.0)))
        end = min(dur, max(start + 0.5, float(sc.get("end", dur))))

        music_meta = None
        raw_music = sc.get("music")
        if isinstance(raw_music, dict) and raw_music.get("assetName"):
            asset_base = os.path.basename(str(raw_music["assetName"]))
            asset_full = os.path.join(assets_dir, asset_base)
            if os.path.isfile(asset_full):
                probed_music_dur = _probe_audio_duration(asset_full)
                saved_music_dur = max(0.0, float(raw_music.get("totalDur") or 0.0))
                real_music_dur = probed_music_dur if probed_music_dur > 0.05 else saved_music_dur
                raw_slice_start = max(0.0, float(raw_music.get("sliceStart") or 0.0))
                if real_music_dur > 0.05:
                    raw_slice_start = min(raw_slice_start, max(0.0, real_music_dur - 0.1))
                music_meta = {
                    "name": str(raw_music.get("name") or asset_base),
                    "assetName": asset_base,
                    "url": f"/api/studio/{project_id}/music/{asset_base}",
                    "totalDur": real_music_dur,
                    "sliceStart": raw_slice_start,
                    "volume": max(0, min(100, int(raw_music.get("volume", 35)))),
                    "peaks": raw_music.get("peaks") if isinstance(raw_music.get("peaks"), list) else [],
                }

        raw_name = os.path.splitext(os.path.basename(clip_path))[0]
        clip_title = str(sc.get("title") if sc.get("title") is not None else (f.get("title") or (f"Clip {idx + 1}" if mode == "ai_clip" else raw_name)))
        clip_caption = str(sc.get("caption") if sc.get("caption") is not None else (f.get("caption") or ""))
        clip_tags = (
            str(sc.get("tags"))
            if sc.get("tags") is not None
            else (_generate_adaptive_hashtags(clip_title, clip_caption) if mode == "ai_clip" else "")
        )

        segments = _sanitize_segments(sc.get("segments"), dur, start, end)
        crop_ratio = _sanitize_crop_ratio(sc.get("cropRatio"))
        fade = _sanitize_fade(sc.get("fade"))
        color = _sanitize_color(sc.get("color"))
        audio_enhance = _sanitize_audio_enhance(sc.get("audioEnhance"))
        tl_total_dur = max(0.5, sum((e - s) / spd for s, e, spd, _, _, _ in _expand_segments_to_pieces(segments)))
        audio_clips = (
            _sanitize_audio_clips(sc.get("audioClips"), project_id, assets_dir, tl_total_dur, legacy_music=music_meta)
            if mode == "full_video"
            else []
        )

        clips.append(
            {
                "id": clip_id,
                "name": f"Clip {idx + 1}" if mode == "ai_clip" else clip_title,
                "filename": os.path.basename(clip_path),
                "title": clip_title,
                "tags": clip_tags,
                "caption": clip_caption,
                "score": f.get("score"),
                "src": _media_vault_url(clip_path),
                "dur": round(dur, 3),
                "start": round(start, 3),
                "end": round(end, 3),
                "cues": cues,
                "music": music_meta,
                "audioClips": audio_clips,
                "audioEnhance": audio_enhance,
                "cropRatio": crop_ratio,
                "fade": fade,
                "color": color,
                "origMuted": bool(sc.get("origMuted", False)),
                "segments": segments,
            }
        )

    return {
        "project_id": project_id,
        "mode": mode,
        "workspace_name": str(proj.get("workspace_name") or proj.get("source_title") or "Workspace"),
        "clips": clips,
        "ui": {
            "subStyle": saved.get("subStyle", "none"),
            "subSize": saved.get("subSize", "medium"),
            "customScale": int(saved.get("customScale", 100)),
            "subPos": saved.get("subPos", "bottom"),
            "posX": float(saved.get("posX", 50)),
            "posY": float(saved.get("posY", 78)),
        },
    }


def save_studio_state(project_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    found = find_studio_project(project_id)
    if not found:
        return None
    _, folder = found
    assets_dir = os.path.join(folder, STUDIO_ASSETS_DIR)

    clean_clips = []
    for c in payload.get("clips") or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        clean_music = None
        m = c.get("music")
        if isinstance(m, dict) and m.get("assetName"):
            clean_peaks: List[float] = []
            if isinstance(m.get("peaks"), list):
                for x in (m.get("peaks") or [])[:256]:
                    fx = _safe_float(x, -1.0)
                    if fx >= 0.0:
                        clean_peaks.append(round(fx, 4))
            clean_music = {
                "name": str(m.get("name") or ""),
                "assetName": os.path.basename(str(m["assetName"])),
                "totalDur": max(0.0, _safe_float(m.get("totalDur"), 0.0)),
                "sliceStart": max(0.0, _safe_float(m.get("sliceStart"), 0.0)),
                "volume": max(0, min(100, _safe_int(m.get("volume"), 35))),
                "peaks": clean_peaks,
            }
        clean_cues = []
        for q in c.get("cues") or []:
            if isinstance(q, dict) and isinstance(q.get("text"), str):
                qs = round(max(0.0, _safe_float(q.get("start"), 0.0)), 3)
                qe = round(max(qs, _safe_float(q.get("end"), qs)), 3)
                cue_item: Dict[str, Any] = {
                    "start": qs,
                    "end": qe,
                    "text": q["text"],
                }
                if q.get("splitTime") is not None:
                    st_val = _safe_float(q.get("splitTime"), -1.0)
                    if qs < st_val < qe:
                        cue_item["splitTime"] = round(st_val, 3)
                clean_cues.append(cue_item)
        dur = round(max(0.0, _safe_float(c.get("dur"), 0.0)), 3)
        start = round(max(0.0, _safe_float(c.get("start"), 0.0)), 3)
        end = round(max(start, _safe_float(c.get("end"), dur)), 3)
        segments = _sanitize_segments(c.get("segments"), dur or max(1.0, end), start, end)
        tl_total_dur = max(0.5, sum((e - s) / spd for s, e, spd, _, _, _ in _expand_segments_to_pieces(segments)))
        raw_audio_clips = c.get("audioClips")
        clean_audio_clips = (
            _sanitize_audio_clips(raw_audio_clips, project_id, assets_dir, tl_total_dur)
            if isinstance(raw_audio_clips, list)
            else None
        )

        clip_doc: Dict[str, Any] = {
            "id": str(c["id"]),
            "dur": dur,
            "start": start,
            "end": end,
            "title": str(c.get("title") or ""),
            "tags": str(c.get("tags") or ""),
            "caption": str(c.get("caption") or ""),
            "cues": clean_cues,
            "music": clean_music,
            "cropRatio": _sanitize_crop_ratio(c.get("cropRatio")),
            "fade": _sanitize_fade(c.get("fade")),
            "color": _sanitize_color(c.get("color")),
            "origMuted": bool(c.get("origMuted", False)),
            "audioEnhance": _sanitize_audio_enhance(c.get("audioEnhance")),
            "segments": segments,
        }
        if clean_audio_clips is not None:
            clip_doc["audioClips"] = clean_audio_clips
        clean_clips.append(clip_doc)

    state_doc = {
        "subStyle": str(payload.get("subStyle") or "none"),
        "subSize": str(payload.get("subSize") or "medium"),
        "customScale": max(0, min(200, _safe_int(payload.get("customScale"), 100))),
        "subPos": str(payload.get("subPos") or "bottom"),
        "posX": max(15.0, min(85.0, _safe_float(payload.get("posX"), 50.0))),
        "posY": max(10.0, min(92.0, _safe_float(payload.get("posY"), 78.0))),
        "clips": clean_clips,
    }
    vault_service._atomic_write_json(os.path.join(folder, STUDIO_STATE_FILE), state_doc)
    return state_doc


def save_studio_music_from_file(
    project_id: str,
    clip_id: str,
    original_filename: str,
    upload_path: str,
    file_size: Optional[int] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    found = find_studio_project(project_id)
    if not found:
        return None, "Project not found"
    _, folder = found
    if not upload_path or not os.path.isfile(upload_path):
        return None, "Empty media file"
    actual_size = os.path.getsize(upload_path) if file_size is None else int(file_size)
    if actual_size <= 0:
        return None, "Empty media file"

    display_name = os.path.basename(original_filename or "music.mp3").strip() or "music.mp3"
    stem, ext_raw = os.path.splitext(display_name)
    ext = ext_raw.lower()
    is_webm_video = ext == ".webm" and _probe_has_video(upload_path)
    is_video_input = (ext in VIDEO_FILE_EXTS and ext != ".webm") or is_webm_video

    if is_video_input:
        if actual_size > MAX_VIDEO_EXTRACT_BYTES:
            return None, "Video file exceeds 250 MB limit for audio extraction"
    elif ext in ALLOWED_AUDIO_EXTS:
        if actual_size > MAX_AUDIO_BYTES:
            return None, "Audio file exceeds 60 MB limit"
    else:
        return None, f"Unsupported audio or video format ({ext or 'unknown'})"

    safe_clip = re.sub(r"[^a-zA-Z0-9_-]", "", clip_id or "clip")[:24] or "clip"
    assets_dir = os.path.join(folder, STUDIO_ASSETS_DIR)
    os.makedirs(assets_dir, exist_ok=True)

    # Extract audio track to MP3 when user uploads a video file (e.g., MP4/MOV/MKV/video-WEBM)
    if is_video_input:
        if not ffmpeg_setup.ensure_ffmpeg():
            return None, "FFmpeg is not available to extract audio from video"
        asset_name = f"{safe_clip}_{uuid.uuid4().hex[:8]}.mp3"
        target = os.path.join(assets_dir, asset_name)
        if not vault_service._is_inside_storage(target, storage_manager.get_storage_root()):
            return None, "Invalid storage path"
        if not _probe_has_audio(upload_path):
            return None, "Selected video has no audio track"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            upload_path,
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            target,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
        except subprocess.TimeoutExpired:
            if os.path.exists(target):
                try:
                    os.remove(target)
                except OSError:
                    pass
            return None, "Audio extraction timed out"
        if res.returncode != 0 or not os.path.isfile(target):
            if os.path.exists(target):
                try:
                    os.remove(target)
                except OSError:
                    pass
            err_tail = (res.stderr or res.stdout or "Audio extraction failed").strip()[-240:]
            return None, f"Could not extract audio from video: {err_tail}"
        probed_dur = _probe_audio_duration(target)
        if probed_dur <= 0.05:
            try:
                os.remove(target)
            except OSError:
                pass
            return None, "Extracted audio track is empty or unreadable"
        out_display = f"{stem or 'extracted'}.mp3"
        return {
            "name": out_display,
            "assetName": asset_name,
            "url": f"/api/studio/{project_id}/music/{asset_name}",
            "duration": probed_dur,
            "peaks": _compute_audio_peaks_ffmpeg(target, 160),
            "extractedFromVideo": True,
        }, None

    asset_name = f"{safe_clip}_{uuid.uuid4().hex[:8]}{ext}"
    target = os.path.join(assets_dir, asset_name)
    if not vault_service._is_inside_storage(target, storage_manager.get_storage_root()):
        return None, "Invalid storage path"

    shutil.copyfile(upload_path, target)
    if ffmpeg_setup.ensure_ffmpeg():
        probed_dur = _probe_audio_duration(target)
        if not _probe_has_audio(target) or probed_dur <= 0.05:
            try:
                os.remove(target)
            except OSError:
                pass
            return None, "Uploaded file is not a valid audio file"
    else:
        probed_dur = 0.0

    return {
        "name": display_name,
        "assetName": asset_name,
        "url": f"/api/studio/{project_id}/music/{asset_name}",
        "duration": probed_dur,
        "peaks": _compute_audio_peaks_ffmpeg(target, 160),
        "extractedFromVideo": False,
    }, None


def save_studio_music(
    project_id: str, clip_id: str, original_filename: str, data: bytes
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not data:
        return None, "Empty media file"
    ext = os.path.splitext(os.path.basename(original_filename or "music.mp3"))[1].lower()
    tmp_path: Optional[str] = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="luna_music_", suffix=ext or ".bin")
        with os.fdopen(fd, "wb") as tf:
            tf.write(data)
        return save_studio_music_from_file(project_id, clip_id, original_filename, tmp_path, len(data))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def get_studio_music_path(project_id: str, asset_name: str) -> Optional[str]:
    found = find_studio_project(project_id)
    if not found:
        return None
    _, folder = found
    base = os.path.basename(asset_name or "")
    if not base or base != asset_name:
        return None
    path = os.path.join(folder, STUDIO_ASSETS_DIR, base)
    if os.path.isfile(path) and vault_service._is_inside_storage(path, storage_manager.get_storage_root()):
        return os.path.abspath(path)
    return None


def _ass_timestamp(sec: float) -> str:
    s = max(0.0, float(sec))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    rem = s % 60
    return f"{h}:{m:02d}:{rem:05.2f}"


def _escape_ass_text(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r", "")
        .replace("\n", r"\N")
    )


def _split_two_balanced_lines(text: str) -> List[str]:
    words = [w for w in str(text or "").strip().split() if w]
    if len(words) <= 2:
        return [" ".join(words)] if words else []
    total = len(text.strip())
    acc = 0
    best_idx = (len(words) + 1) // 2
    best_diff = 10**9
    for i in range(1, len(words)):
        acc += len(words[i - 1]) + 1
        diff = abs(acc - total / 2.0)
        if diff < best_diff:
            best_diff = diff
            best_idx = i
    return [" ".join(words[:best_idx]), " ".join(words[best_idx:])]


def _build_selene_ass(
    cues: List[Dict[str, Any]],
    trim_start: float,
    trim_end: float,
    width: int,
    height: int,
    size_scale: float,
    pos_x_pct: float,
    pos_y_pct: float,
) -> str:
    font_px = max(14, int(round(height * 0.034 * size_scale)))
    pos_x = int(round((pos_x_pct / 100.0) * width))
    pos_y = int(round((pos_y_pct / 100.0) * height))

    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Selene,Montserrat,{font_px},&H00FFFFFF,&H00FFFFFF,&H70000000,&H90000000,0,0,0,0,100,100,-0.4,0,1,1.2,2.2,5,36,36,24,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    events: List[str] = []
    valid_cues = [
        q for q in cues if isinstance(q, dict) and str(q.get("text") or "").strip()
    ]
    # Skip a tiny stray boundary stub right at t=0 without pulling the next cue earlier
    if (
        len(valid_cues) > 1
        and float(valid_cues[0].get("start", 0.0)) < 0.05
        and (float(valid_cues[0].get("end", 0.0)) - float(valid_cues[0].get("start", 0.0))) < 0.20
    ):
        valid_cues = valid_cues[1:]

    for q in valid_cues:
        q_start = max(trim_start, float(q.get("start", 0.0)))
        q_end = min(trim_end, float(q.get("end", 0.0)))
        if q_end <= q_start + 0.02:
            continue
        rel_start = q_start - trim_start
        rel_end = q_end - trim_start
        lines = _split_two_balanced_lines(str(q.get("text") or ""))
        if not lines:
            continue
        pos_tag = rf"{{\an5\pos({pos_x},{pos_y})}}"
        if len(lines) == 1:
            txt = rf"{pos_tag}{{\b1}}{_escape_ass_text(lines[0])}"
            events.append(f"Dialogue: 0,{_ass_timestamp(rel_start)},{_ass_timestamp(rel_end)},Selene,,0,0,0,,{txt}")
        else:
            raw_split = q.get("splitTime")
            split_abs = _safe_float(raw_split, -1.0) if raw_split is not None else -1.0
            if q_start + 0.02 < split_abs < q_end - 0.02:
                mid = split_abs - trim_start
            else:
                char_ratio = max(0.25, min(0.75, len(lines[0]) / max(1, len(lines[0]) + len(lines[1]))))
                mid = rel_start + (rel_end - rel_start) * char_ratio
            l1 = _escape_ass_text(lines[0])
            l2 = _escape_ass_text(lines[1])
            # First half: line 1 bold, line 2 regular
            t1 = rf"{pos_tag}{{\b1\alpha&H00&}}{l1}\N{{\b0\alpha&H1E&}}{l2}"
            # Second half: line 1 regular, line 2 bold
            t2 = rf"{pos_tag}{{\b0\alpha&H1E&}}{l1}\N{{\b1\alpha&H00&}}{l2}"
            events.append(f"Dialogue: 0,{_ass_timestamp(rel_start)},{_ass_timestamp(mid)},Selene,,0,0,0,,{t1}")
            events.append(f"Dialogue: 0,{_ass_timestamp(mid)},{_ass_timestamp(rel_end)},Selene,,0,0,0,,{t2}")

    return header + "\n" + "\n".join(events) + "\n"


def _escape_ffmpeg_filter_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _probe_has_audio(video_path: str) -> bool:
    if not ffmpeg_setup.ensure_ffmpeg():
        return True
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            video_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        return res.returncode == 0 and bool(res.stdout.strip())
    except Exception:
        return True


def _sample_curve_speed(
    points: List[float], ratio: float, positions: Optional[List[float]] = None
) -> float:
    """Linearly interpolate a 5-point 2D speed curve at normalized position ratio in [0, 1]."""
    pts = _sanitize_curve_points(points)
    pos = _sanitize_curve_positions(positions)
    r = max(0.0, min(1.0, float(ratio)))
    for i in range(4):
        if r <= pos[i + 1] + 1e-6 or i == 3:
            span = max(0.001, pos[i + 1] - pos[i])
            frac = max(0.0, min(1.0, (r - pos[i]) / span))
            return round(max(0.25, min(4.0, pts[i] * (1.0 - frac) + pts[i + 1] * frac)), 3)
    return round(pts[-1], 3)


def _expand_segments_to_pieces(
    segments: List[Dict[str, Any]],
) -> List[Tuple[float, float, float, float, float, float]]:
    """Expand timeline block segments (normal or 2D 5-point speed curve) into atomic (start, end, speed, vol, crop_x, crop_y) pieces."""
    pieces: List[Tuple[float, float, float, float, float, float]] = []
    for seg in segments:
        ss = float(seg["sourceStart"])
        se = float(seg["sourceEnd"])
        if se - ss < 0.1:
            continue
        vol = max(0.0, min(1.0, float(seg.get("volume", 100)) / 100.0))
        cx = round(max(0.0, min(100.0, float(seg.get("cropX", 50.0)))), 1)
        cy = round(max(0.0, min(100.0, float(seg.get("cropY", 50.0)))), 1)
        smode = seg.get("speedMode", "normal")
        if smode == "curve":
            pts = _sanitize_curve_points(seg.get("curvePoints"))
            pos = _sanitize_curve_positions(seg.get("curvePositions"))
            is_flat = all(abs(p - pts[0]) < 0.02 for p in pts)
            if is_flat:
                pieces.append((round(ss, 3), round(se, 3), round(pts[0], 3), vol, cx, cy))
            else:
                steps = max(1, min(10, int((se - ss) / 0.2)))
                step_dur = (se - ss) / steps
                for k in range(steps):
                    a = ss + k * step_dur
                    b = ss + (k + 1) * step_dur
                    mid_ratio = (k + 0.5) / steps
                    spd = _sample_curve_speed(pts, mid_ratio, pos)
                    if (
                        pieces
                        and abs(pieces[-1][1] - a) < 0.005
                        and abs(pieces[-1][2] - spd) < 0.02
                        and abs(pieces[-1][3] - vol) < 0.005
                        and abs(pieces[-1][4] - cx) < 0.05
                        and abs(pieces[-1][5] - cy) < 0.05
                    ):
                        pieces[-1] = (pieces[-1][0], round(b, 3), spd, vol, cx, cy)
                    else:
                        pieces.append((round(a, 3), round(b, 3), spd, vol, cx, cy))
        else:
            spd = round(max(0.25, min(4.0, float(seg.get("speed", 1.0)))), 3)
            pieces.append((round(ss, 3), round(se, 3), spd, vol, cx, cy))
    return pieces


def _atempo_chain(speed: float) -> str:
    spd = max(0.25, min(4.0, float(speed)))
    if abs(spd - 1.0) < 0.01:
        return ""
    factors: List[float] = []
    rem = spd
    while rem < 0.5:
        factors.append(0.5)
        rem /= 0.5
    while rem > 2.0:
        factors.append(2.0)
        rem /= 2.0
    if abs(rem - 1.0) >= 0.005 or not factors:
        factors.append(rem)
    return ",".join(f"atempo={f:.4f}" for f in factors)


def _build_crop_filter(
    crop_ratio: str,
    width: int,
    height: int,
    crop_x: float = 50.0,
    crop_y: float = 50.0,
) -> Optional[str]:
    ratios = {
        "16:9": 16.0 / 9.0,
        "9:16": 9.0 / 16.0,
        "1:1": 1.0,
        "3:4": 3.0 / 4.0,
    }
    target = ratios.get(crop_ratio)
    if not target or width <= 0 or height <= 0:
        return None
    cur = width / float(height)
    if abs(cur - target) < 0.015:
        return None
    if cur > target:
        ow = int(round(height * target))
        oh = height
    else:
        ow = width
        oh = int(round(width / target))
    ow = max(2, ow - (ow % 2))
    oh = max(2, oh - (oh % 2))
    cx = max(0.0, min(100.0, float(crop_x)))
    cy = max(0.0, min(100.0, float(crop_y)))
    if abs(cx - 50.0) < 0.05 and abs(cy - 50.0) < 0.05:
        return f"crop={ow}:{oh}:(iw-{ow})/2:(ih-{oh})/2"
    ox = max(0, min(width - ow, int(round((width - ow) * (cx / 100.0)))))
    oy = max(0, min(height - oh, int(round((height - oh) * (cy / 100.0)))))
    return f"crop={ow}:{oh}:{ox}:{oy}"


def _build_color_filters(color_cfg: Dict[str, Any]) -> List[str]:
    preset = str(color_cfg.get("preset") or "natural").lower()
    b_val = int(color_cfg.get("brightness") or 0)
    c_val = int(color_cfg.get("contrast") or 0)
    s_val = int(color_cfg.get("saturation") or 0)
    exp_val = int(color_cfg.get("exposure") or 0)
    warm_val = int(color_cfg.get("warmth") or 0)
    sharp_val = max(0, int(color_cfg.get("sharpness") or 0))
    vig_val = max(0, int(color_cfg.get("vignette") or 0))
    filters: List[str] = []

    gamma = round(max(0.45, min(2.4, 2.0 ** (exp_val / 80.0))), 3)
    if preset == "bw":
        eq_b = b_val / 200.0
        eq_c = 1.0 + (c_val / 100.0)
        filters.append(f"eq=brightness={eq_b:.3f}:contrast={eq_c:.3f}:saturation=0.000:gamma={gamma:.3f}")
    elif b_val != 0 or c_val != 0 or s_val != 0 or exp_val != 0:
        eq_b = b_val / 200.0
        eq_c = 1.0 + (c_val / 100.0)
        eq_s = max(0.0, 1.0 + (s_val / 50.0))
        filters.append(f"eq=brightness={eq_b:.3f}:contrast={eq_c:.3f}:saturation={eq_s:.3f}:gamma={gamma:.3f}")

    if preset != "bw":
        # Pure-YUV chroma warmth shift (avoids 4x slower YUV->RGB->YUV colorbalance conversion)
        warm_shift = warm_val * 0.35 + (
            6.0 if preset == "warm" else (-4.0 if preset == "cinematic" else 0.0)
        )
        du = int(round(max(-24.0, min(24.0, -warm_shift * 0.85))))
        dv = int(round(max(-24.0, min(24.0, warm_shift * 0.95))))
        if du != 0 or dv != 0:
            u_expr = f"val{du:+d}" if du != 0 else "val"
            v_expr = f"val{dv:+d}" if dv != 0 else "val"
            filters.append(f"lutyuv=y=val:u={u_expr}:v={v_expr}")

    if sharp_val > 0:
        amt = round(min(2.0, sharp_val / 24.0), 2)
        filters.append(f"unsharp=3:3:{amt:.2f}:3:3:0.0")

    if vig_val > 0:
        angle = round(min(1.2, (vig_val / 50.0) * 1.15), 3)
        filters.append(f"vignette=angle={angle:.3f}")

    return filters


def _resolve_project_clip(project_id: str, clip_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    found = find_studio_project(project_id)
    if not found:
        return None, None, None, None, "Project not found"
    proj, folder = found
    target_file = None
    video_files = [
        f for f in (proj.get("files") or []) if isinstance(f, dict) and _is_video_file_record(f)
    ]
    for idx, f in enumerate(video_files):
        if str(f.get("id") or f"clip_{idx + 1}") == clip_id:
            target_file = f
            break
    if not target_file:
        # Fallback direct id match in case a legacy record had non-standard metadata
        for f in proj.get("files") or []:
            if isinstance(f, dict) and str(f.get("id") or "") == clip_id:
                target_file = f
                break
    if not target_file:
        return None, None, None, None, "Clip not found"
    src_path = _resolve_clip_path(target_file, folder)
    if not src_path:
        return None, None, None, None, "Source clip file is missing on disk"
    return proj, folder, target_file, src_path, None


_TIME_STDERR_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_HW_ENCODER_CACHE: Optional[Tuple[str, List[str]]] = None
_HW_ENCODER_LOCK = threading.Lock()
_HW_DECODER_CACHE: Optional[Tuple[str, List[str]]] = None
_HW_DECODER_LOCK = threading.Lock()


def _get_hwaccel_input_args() -> List[str]:
    """Auto-detect a working hardware video decoder (D3D11VA/CUDA/VideoToolbox/VAAPI/QSV) once."""
    global _HW_DECODER_CACHE
    with _HW_DECODER_LOCK:
        if _HW_DECODER_CACHE is not None:
            return list(_HW_DECODER_CACHE[1])
        try:
            probe = subprocess.run(
                ["ffmpeg", "-hide_banner", "-hwaccels"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            avail = {ln.strip().lower() for ln in (probe.stdout or "").splitlines() if ln.strip()}
        except Exception:
            avail = set()

        # Prefer CUDA decode when NVIDIA NVENC is the active encoder so zero-copy VRAM works on Windows
        enc_args_hint = _get_fast_h264_encoder_args()
        enc_hint = enc_args_hint[1] if len(enc_args_hint) > 1 else ""
        pref_order = (
            ("cuda", "d3d11va", "videotoolbox", "vaapi", "qsv")
            if enc_hint == "h264_nvenc"
            else ("d3d11va", "cuda", "videotoolbox", "vaapi", "qsv")
        )
        candidates = [a for a in pref_order if a in avail]
        if candidates:
            try:
                with tempfile.TemporaryDirectory(prefix="luna_hwprobe_", ignore_cleanup_errors=True) as td:
                    tmp_mp4 = os.path.join(td, "probe.mp4")
                    gen = subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-f",
                            "lavfi",
                            "-i",
                            "color=c=black:s=128x128:d=0.1",
                            "-c:v",
                            "libx264",
                            "-preset",
                            "ultrafast",
                            "-pix_fmt",
                            "yuv420p",
                            tmp_mp4,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=6,
                        check=False,
                    )
                    if gen.returncode == 0 and os.path.isfile(tmp_mp4):
                        for accel in candidates:
                            try:
                                dec = subprocess.run(
                                    ["ffmpeg", "-y", "-hwaccel", accel, "-i", tmp_mp4, "-f", "null", "-"],
                                    capture_output=True,
                                    text=True,
                                    timeout=6,
                                    check=False,
                                )
                                if dec.returncode == 0:
                                    _HW_DECODER_CACHE = (accel, ["-hwaccel", accel])
                                    return ["-hwaccel", accel]
                            except Exception:
                                continue
            except Exception:
                pass
        _HW_DECODER_CACHE = ("none", [])
        return []


def _get_fast_h264_encoder_args() -> List[str]:
    """Auto-detect a working high-quality hardware H.264 encoder across NVIDIA/Intel/AMD/Apple, or multi-threaded libx264."""
    global _HW_ENCODER_CACHE
    with _HW_ENCODER_LOCK:
        if _HW_ENCODER_CACHE is not None:
            return list(_HW_ENCODER_CACHE[1])
        candidates = [
            ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "19", "-b:v", "0", "-pix_fmt", "yuv420p"]),
            ("h264_qsv", ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "19", "-pix_fmt", "nv12"]),
            ("h264_amf", ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "18", "-qp_p", "18", "-pix_fmt", "yuv420p"]),
            ("h264_videotoolbox", ["-c:v", "h264_videotoolbox", "-q:v", "65", "-pix_fmt", "yuv420p"]),
        ]
        for name, enc_args in candidates:
            try:
                probe = subprocess.run(
                    ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=128x128:d=0.1", *enc_args, "-f", "null", "-"],
                    capture_output=True,
                    text=True,
                    timeout=6,
                    check=False,
                )
                if probe.returncode == 0:
                    _HW_ENCODER_CACHE = (name, enc_args)
                    return list(enc_args)
            except Exception:
                continue
        fallback = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "0", "-pix_fmt", "yuv420p"]
        _HW_ENCODER_CACHE = ("libx264", fallback)
        return list(fallback)


def _group_pieces_for_fast_seek(
    pieces: List[Tuple[float, float, float, float, float, float]],
    max_gap: float = 2.0,
    max_groups: int = 16,
) -> List[Dict[str, Any]]:
    """Group contiguous/nearby timeline pieces into bounded fast-seek input ranges.

    Each group becomes its own ``-ss <start> -t <span> -i <src>`` input so FFmpeg
    skips discarded gaps and trailing footage at the demuxer level instead of
    CPU-decoding the full video from 00:00.
    """
    if not pieces:
        return []

    groups: List[Dict[str, Any]] = []
    for idx, piece in enumerate(pieces):
        ps, pe = float(piece[0]), float(piece[1])
        if (
            groups
            and ps >= groups[-1]["end"] - 0.05
            and (ps - groups[-1]["end"]) <= max_gap
        ):
            groups[-1]["end"] = max(groups[-1]["end"], pe)
            groups[-1]["items"].append((idx, piece))
        else:
            groups.append({"start": ps, "end": pe, "items": [(idx, piece)]})

    # If many discontiguous fragments exist, merge smallest monotonic gaps to cap open file handles
    while len(groups) > max_groups:
        best_i = -1
        best_gap = float("inf")
        for i in range(len(groups) - 1):
            gap = groups[i + 1]["start"] - groups[i]["end"]
            if gap >= -0.05 and gap < best_gap:
                best_gap = gap
                best_i = i
        if best_i < 0:
            # Non-monotonic pieces: collapse to a single bounded range
            g_start = min(g["start"] for g in groups)
            g_end = max(g["end"] for g in groups)
            all_items = [it for g in groups for it in g["items"]]
            return [{"start": g_start, "end": g_end, "items": all_items}]
        merged = {
            "start": min(groups[best_i]["start"], groups[best_i + 1]["start"]),
            "end": max(groups[best_i]["end"], groups[best_i + 1]["end"]),
            "items": groups[best_i]["items"] + groups[best_i + 1]["items"],
        }
        groups[best_i : best_i + 2] = [merged]

    return groups


def _escape_concat_path(path: str) -> str:
    return path.replace("\\", "/").replace("'", "'\\''")


def _concat_segments_lossless(
    src_path: str,
    pieces: List[Tuple[float, float, float, float, float, float]],
    out_path: str,
    *,
    has_src_audio: bool,
    muted: bool,
    has_vol_change: bool,
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel_ctx: Optional[Dict[str, Any]] = None,
    pct_range: Tuple[int, int] = (1, 95),
) -> Tuple[bool, bool]:
    """Lossless multi-segment video copy (-c:v copy) + FFmpeg concat demuxer.

    Returns ``(ok, cancelled)``. Returns ``(False, False)`` if any segment cannot be
    cleanly stream-copied (e.g. single-keyframe synthetic video), letting the caller
    fall back cleanly to Tier 3 render.
    """
    p_lo, p_hi = pct_range
    total_span = max(0.2, sum(max(0.1, pe - ps) for ps, pe, _, _, _, _ in pieces))
    cancel_ev: Optional[threading.Event] = cancel_ctx.get("event") if isinstance(cancel_ctx, dict) else None

    with tempfile.TemporaryDirectory(prefix="luna_concat_", ignore_cleanup_errors=True) as td:
        seg_files: List[str] = []
        done_span = 0.0
        for i, (ps, pe, _, vol, _, _) in enumerate(pieces):
            if cancel_ev and cancel_ev.is_set():
                return False, True
            span = max(0.1, pe - ps)
            seg_out = os.path.join(td, f"seg_{i:03d}.mp4")
            cmd: List[str] = [
                "ffmpeg",
                "-y",
                "-ss",
                f"{ps:.3f}",
                "-t",
                f"{span:.3f}",
                "-i",
                src_path,
                "-map",
                "0:v:0",
                "-c:v",
                "copy",
            ]
            if muted or not has_src_audio:
                cmd += ["-an"]
            elif has_vol_change:
                v_gain = 0.0 if vol <= 0.001 else vol
                cmd += [
                    "-map", "0:a:0",
                    "-af", f"volume={v_gain:.3f}",
                    "-c:a", "aac",
                    "-ar", "48000",
                    "-ac", "2",
                    "-b:a", "192k",
                ]
            else:
                cmd += ["-map", "0:a:0", "-c:a", "copy"]
            cmd += ["-avoid_negative_ts", "make_zero", seg_out]

            base_done = done_span
            seg_pct_lo = p_lo + int((base_done / total_span) * max(1, p_hi - p_lo - 10))
            seg_pct_hi = p_lo + int(((base_done + span) / total_span) * max(1, p_hi - p_lo - 10))

            def _seg_prog(pct: int, lo: int = seg_pct_lo, hi: int = seg_pct_hi) -> None:
                if progress_cb is not None:
                    mapped = lo + int((pct / 100.0) * max(1, hi - lo))
                    progress_cb(min(p_hi - 5, max(1, mapped)))

            res = _run_ffmpeg_with_progress(
                cmd, span, progress_cb=_seg_prog if progress_cb else None, cancel_ctx=cancel_ctx, timeout=300
            )
            if res.returncode == -2:
                return False, True
            if res.returncode != 0 or not os.path.isfile(seg_out) or os.path.getsize(seg_out) < 256:
                return False, False
            # Bail out early if keyframe pre-roll caused severe A/V desync when re-encoding per-segment audio
            if has_vol_change and ps > 0.05:
                seg_actual_dur, _, _ = _probe_video_info(seg_out)
                if seg_actual_dur <= 0.05 or abs(seg_actual_dur - span) > 0.35:
                    return False, False
            seg_files.append(seg_out)
            done_span += span
            if progress_cb is not None:
                progress_cb(min(p_hi - 5, max(1, seg_pct_hi)))

        if cancel_ev and cancel_ev.is_set():
            return False, True

        list_path = os.path.join(td, "concat.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for sf in seg_files:
                f.write(f"file '{_escape_concat_path(sf)}'\n")

        concat_cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_path,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            out_path,
        ]
        res_cat = _run_ffmpeg_with_progress(
            concat_cmd, total_span, progress_cb=None, cancel_ctx=cancel_ctx, timeout=300
        )
        if res_cat.returncode == -2:
            return False, True
        if res_cat.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) < 256:
            return False, False

        # Tight duration check so non-keyframe cuts (e.g. Auto Cut Silence) fall back to frame-accurate Tier 3
        actual_dur, _, _ = _probe_video_info(out_path)
        max_tol = max(0.45, min(1.5, len(pieces) * 0.25))
        if actual_dur <= 0.15 or abs(actual_dur - total_span) > max_tol:
            try:
                os.remove(out_path)
            except OSError:
                pass
            return False, False

        if progress_cb is not None:
            progress_cb(min(99, max(1, p_hi)))
        return True, False


_CANCEL_CTX_FALLBACK_LOCK = threading.Lock()


def _get_ctx_lock(cancel_ctx: Optional[Dict[str, Any]]) -> threading.Lock:
    if isinstance(cancel_ctx, dict):
        lk = cancel_ctx.get("lock")
        if lk is not None:
            return lk
    return _CANCEL_CTX_FALLBACK_LOCK


def _run_ffmpeg_with_progress(
    cmd: List[str],
    total_dur_sec: float,
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel_ctx: Optional[Dict[str, Any]] = None,
    timeout: int = 1800,
    low_priority: bool = False,
) -> subprocess.CompletedProcess:
    """Run an FFmpeg command with unbuffered real-time 1..99% progress, watchdog timeout, and instant cancel."""
    if progress_cb is None and cancel_ctx is None and not low_priority:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, -1, stdout="", stderr="FFmpeg timed out")
    if len(cmd) < 2:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, -1, stdout="", stderr="FFmpeg timed out")

    cancel_ev: Optional[threading.Event] = cancel_ctx.get("event") if isinstance(cancel_ctx, dict) else None
    if cancel_ev and cancel_ev.is_set():
        return subprocess.CompletedProcess(cmd, -2, stdout="", stderr="Cancelled")

    # Inject -progress pipe:1 right before the output path (last arg); keep stderr stats as fallback
    prog_cmd = list(cmd[:-1]) + ["-progress", "pipe:1", cmd[-1]]
    popen_kwargs: Dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "bufsize": 0,
    }
    if low_priority:
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)
        elif hasattr(os, "nice"):
            popen_kwargs["preexec_fn"] = lambda: os.nice(10)
    proc = subprocess.Popen(prog_cmd, **popen_kwargs)
    ctx_lock = _get_ctx_lock(cancel_ctx)
    if isinstance(cancel_ctx, dict):
        with ctx_lock:
            cancel_ctx["proc"] = proc
            procs_set = cancel_ctx.get("procs")
            if isinstance(procs_set, set):
                procs_set.add(proc)
            if cancel_ev and cancel_ev.is_set():
                try:
                    proc.kill()
                except Exception:
                    pass

    timed_out = [False]

    def _on_timeout() -> None:
        timed_out[0] = True
        try:
            proc.kill()
        except Exception:
            pass

    watchdog: Optional[threading.Timer] = None
    if timeout and timeout > 0:
        watchdog = threading.Timer(float(timeout), _on_timeout)
        watchdog.daemon = True
        watchdog.start()

    last_pct = [0]
    pct_lock = threading.Lock()
    total_us = max(100_000.0, float(max(0.1, total_dur_sec)) * 1_000_000.0)
    total_s = max(0.1, float(total_dur_sec))

    def _emit_pct(pct: int) -> None:
        if progress_cb is None:
            return
        clamped = int(min(99, max(1, pct)))
        with pct_lock:
            if clamped > last_pct[0]:
                last_pct[0] = clamped
                try:
                    progress_cb(clamped)
                except Exception:
                    pass

    stderr_chunks: List[str] = []

    def _drain_stderr() -> None:
        if not proc.stderr:
            return
        try:
            buf = b""
            while True:
                chunk = proc.stderr.read(512)
                if not chunk:
                    break
                text_part = chunk.decode("utf-8", errors="replace")
                stderr_chunks.append(text_part)
                if progress_cb is not None:
                    buf += chunk
                    if len(buf) > 2048:
                        buf = buf[-1024:]
                    m = None
                    for m in _TIME_STDERR_RE.finditer(buf.decode("utf-8", errors="replace")):
                        pass
                    if m:
                        cur_s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                        _emit_pct(int(round((cur_s / total_s) * 100)))
        except Exception:
            pass

    err_thread = threading.Thread(target=_drain_stderr, daemon=True)
    err_thread.start()

    try:
        if proc.stdout:
            while True:
                if (cancel_ev and cancel_ev.is_set()) or timed_out[0]:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break
                raw_line = proc.stdout.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    val = line.split("=", 1)[1].strip()
                    if val.isdigit():
                        _emit_pct(int(round((int(val) / total_us) * 100)))
                elif line.startswith("out_time="):
                    hms = line.split("=", 1)[1].strip()
                    parts = hms.split(":")
                    if len(parts) == 3:
                        try:
                            cur_s = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                            _emit_pct(int(round((cur_s / total_s) * 100)))
                        except Exception:
                            pass
        ret = proc.wait(timeout=max(5, timeout))
    except subprocess.TimeoutExpired:
        timed_out[0] = True
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        ret = -1
        stderr_chunks.append("FFmpeg timed out")
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        if isinstance(cancel_ctx, dict):
            with ctx_lock:
                if cancel_ctx.get("proc") is proc:
                    cancel_ctx["proc"] = None
                procs_set = cancel_ctx.get("procs")
                if isinstance(procs_set, set):
                    procs_set.discard(proc)
        err_thread.join(timeout=5)
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except Exception:
                    pass
    if timed_out[0] and not (cancel_ev and cancel_ev.is_set()):
        if "FFmpeg timed out" not in "".join(stderr_chunks):
            stderr_chunks.append("FFmpeg timed out")
        ret = -1
    if cancel_ev and cancel_ev.is_set():
        # Remove partial output file cleanly
        try:
            out_file = cmd[-1]
            if out_file and os.path.isfile(out_file):
                os.remove(out_file)
        except OSError:
            pass
        return subprocess.CompletedProcess(prog_cmd, -2, stdout="", stderr="Cancelled")
    return subprocess.CompletedProcess(prog_cmd, ret, stdout="", stderr="".join(stderr_chunks))


_EXPORT_CACHE_SCHEMA = "v3_hq_yuv_gpu"


def _file_stat_sig(path: str) -> List[Any]:
    try:
        st = os.stat(path)
        return [os.path.abspath(path), int(st.st_size), int(st.st_mtime_ns)]
    except OSError:
        return [os.path.abspath(path), 0, 0]


def _compute_export_cache_key(
    mode: str,
    src_path: str,
    spec: Dict[str, Any],
    extra_asset_paths: Optional[List[str]] = None,
) -> str:
    payload = {
        "schema": _EXPORT_CACHE_SCHEMA,
        "mode": mode,
        "src": _file_stat_sig(src_path),
        "assets": [_file_stat_sig(p) for p in (extra_asset_paths or [])],
        "spec": spec,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _export_cache_meta_path(out_path: str) -> str:
    return f"{out_path}.cache.json"


def _try_reuse_cached_export(out_path: str, cache_key: str) -> bool:
    if not out_path or not cache_key or not os.path.isfile(out_path):
        return False
    try:
        if os.path.getsize(out_path) < 1024:
            return False
        meta_path = _export_cache_meta_path(out_path)
        if not os.path.isfile(meta_path):
            return False
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return isinstance(meta, dict) and meta.get("key") == cache_key
    except Exception:
        return False


_EXPORT_FILE_LOCKS_GUARD = threading.Lock()
_EXPORT_FILE_LOCKS: Dict[str, threading.Lock] = {}


def _get_export_file_lock(out_path: str) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(out_path))
    with _EXPORT_FILE_LOCKS_GUARD:
        lock = _EXPORT_FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _EXPORT_FILE_LOCKS[key] = lock
        return lock


def _save_export_cache_meta(out_path: str, cache_key: str) -> None:
    if not out_path or not cache_key:
        return
    try:
        meta_path = _export_cache_meta_path(out_path)
        tmp_path = f"{meta_path}.{uuid.uuid4().hex[:8]}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"key": cache_key, "created_at": time.time()}, f)
        os.replace(tmp_path, meta_path)
    except Exception:
        pass


def _commit_rendered_export(tmp_out: str, out_path: str, cache_key: str) -> bool:
    """Atomically promote a completed temp render file to out_path and write its cache key."""
    if not tmp_out or not os.path.isfile(tmp_out):
        return False
    lock = _get_export_file_lock(out_path)
    with lock:
        replaced = False
        for attempt in range(5):
            try:
                os.replace(tmp_out, out_path)
                replaced = True
                break
            except PermissionError:
                if attempt == 4:
                    break
                time.sleep(0.12)
            except OSError:
                break
        if not replaced:
            return False
        _save_export_cache_meta(out_path, cache_key)
        return True


def _render_tier3_parallel_chunks(
    project_id: str,
    src_path: str,
    out_path: str,
    seg_s: float,
    seg_e: float,
    seg_vol: float,
    crop_filter: Optional[str],
    color_filters: List[str],
    fade: float,
    use_src_audio: bool,
    audio_clips: List[Dict[str, Any]],
    enc_args: List[str],
    *,
    audio_enhance: Optional[Dict[str, bool]] = None,
    needs_even_scale: bool = False,
    progress_cb: Optional[Callable[[int], None]] = None,
    stage_cb: Optional[Callable[[str], None]] = None,
    cancel_ctx: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, bool]:
    """Encode a long 1.0x single-segment video in parallel GPU/CPU chunks, then losslessly join + mux continuous audio.

    Keeping audio completely unsplit eliminates chunk-boundary AAC delay/clicks while
    multiplying video filter + encode throughput by 2-3x on long 60fps videos.
    Returns ``(ok, cancelled)``.
    """
    span = max(0.2, seg_e - seg_s)
    enc_name = enc_args[1] if len(enc_args) > 1 else "libx264"
    # Balanced concurrency across every platform: 3 workers for >=60s on GPU (NVENC/QSV/AMF/VideoToolbox),
    # 2 workers for 20..60s or CPU-only libx264 (with balanced threads per worker).
    if enc_name in ("h264_amf", "h264_nvenc", "h264_qsv", "h264_videotoolbox"):
        n_workers = 3 if span >= 60.0 else 2
    else:
        n_workers = 2
    worker_enc_args = list(enc_args)
    if enc_name == "libx264":
        per_worker_threads = max(2, (os.cpu_count() or 4) // n_workers)
        if "-threads" in worker_enc_args:
            t_idx = worker_enc_args.index("-threads")
            if t_idx + 1 < len(worker_enc_args):
                worker_enc_args[t_idx + 1] = str(per_worker_threads)
        else:
            worker_enc_args += ["-threads", str(per_worker_threads)]
    chunk_span = span / n_workers
    cancel_ev: Optional[threading.Event] = cancel_ctx.get("event") if isinstance(cancel_ctx, dict) else None
    chunk_cancel_ctx: Dict[str, Any] = {
        "event": threading.Event(),
        "proc": None,
        "procs": set(),
        "lock": threading.Lock(),
    }
    parent_lock = _get_ctx_lock(cancel_ctx)
    if isinstance(cancel_ctx, dict):
        with parent_lock:
            children = cancel_ctx.setdefault("children", [])
            children.append(chunk_cancel_ctx)
            if cancel_ev and cancel_ev.is_set():
                chunk_cancel_ctx["event"].set()

    chunk_pcts = [0] * n_workers
    pct_lock = threading.Lock()

    def _report_agg() -> None:
        if progress_cb is None:
            return
        with pct_lock:
            avg = sum(chunk_pcts) / float(n_workers)
        progress_cb(min(94, max(1, int(round(avg * 0.94)))))

    try:
        with tempfile.TemporaryDirectory(prefix="luna_pchunk_", ignore_cleanup_errors=True) as td:
            chunk_paths = [os.path.join(td, f"chunk_{i:02d}.mp4") for i in range(n_workers)]

            def _encode_chunk(idx: int) -> Tuple[int, int]:
                if (cancel_ev and cancel_ev.is_set()) or chunk_cancel_ctx["event"].is_set():
                    return idx, -2
                c_start = seg_s + idx * chunk_span
                c_end = seg_e if idx == n_workers - 1 else (seg_s + (idx + 1) * chunk_span)
                c_dur = max(0.2, c_end - c_start)

                vf_parts: List[str] = []
                if crop_filter:
                    vf_parts.append(crop_filter)
                elif needs_even_scale:
                    vf_parts.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
                vf_parts.extend(color_filters)
                if fade > 0.0 and span > fade * 2.05:
                    if idx == 0:
                        vf_parts.append(f"fade=t=in:st=0:d={fade:.2f}")
                    if idx == n_workers - 1:
                        local_out_st = max(0.0, c_dur - fade)
                        vf_parts.append(f"fade=t=out:st={local_out_st:.3f}:d={fade:.2f}")

                cmd_c: List[str] = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{c_start:.3f}",
                    "-t",
                    f"{c_dur:.3f}",
                    "-i",
                    src_path,
                ]
                if vf_parts:
                    cmd_c += ["-vf", ",".join(vf_parts)]
                cmd_c += ["-an"] + list(worker_enc_args) + ["-avoid_negative_ts", "make_zero", chunk_paths[idx]]

                def _on_c_pct(p: int) -> None:
                    with pct_lock:
                        if p > chunk_pcts[idx]:
                            chunk_pcts[idx] = p
                    _report_agg()

                res_c = _run_ffmpeg_with_progress(
                    cmd_c, c_dur, progress_cb=_on_c_pct if progress_cb else None, cancel_ctx=chunk_cancel_ctx, timeout=1200
                )
                if res_c.returncode == 0:
                    with pct_lock:
                        chunk_pcts[idx] = 100
                    _report_agg()
                return idx, res_c.returncode

            if stage_cb:
                stage_cb(f"Rendering video ({n_workers}x parallel)...")

            results: List[Tuple[int, int]] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
                futs = [pool.submit(_encode_chunk, i) for i in range(n_workers)]
                for fut in concurrent.futures.as_completed(futs):
                    try:
                        idx_done, rc_done = fut.result()
                    except Exception:
                        idx_done, rc_done = -1, -1
                    results.append((idx_done, rc_done))
                    if rc_done != 0:
                        _kill_cancel_ctx(chunk_cancel_ctx)

            if cancel_ev and cancel_ev.is_set():
                return False, True
            if any(rc != 0 for _, rc in results) or any(
                not os.path.isfile(p) or os.path.getsize(p) < 256 for p in chunk_paths
            ):
                return False, False

            list_path = os.path.join(td, "chunks.txt")
            with open(list_path, "w", encoding="utf-8") as f:
                for cp in chunk_paths:
                    f.write(f"file '{_escape_concat_path(cp)}'\n")

            if stage_cb:
                stage_cb("Finalizing video...")

            # Mux losslessly concatenated video chunks with continuous unsplit audio (zero boundary clicks)
            cmd_mux: List[str] = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path]
            fc_mux: List[str] = []
            a_cur: Optional[str] = None
            next_inp = 1

            ae_cfg = _sanitize_audio_enhance(audio_enhance)
            voice_fx = _build_voice_enhance_filters(ae_cfg)
            if use_src_audio:
                cmd_mux += ["-vn", "-ss", f"{seg_s:.3f}", "-t", f"{span:.3f}", "-i", src_path]
                a_chain = ["asetpts=PTS-STARTPTS"]
                if abs(seg_vol - 1.0) >= 0.005:
                    a_chain.append(f"volume={seg_vol:.3f}")
                a_chain.extend(voice_fx)
                fc_mux.append(f"[{next_inp}:a:0]{','.join(a_chain)}[a0]")
                a_cur = "[a0]"
                next_inp += 1

            af_fade = ""
            if fade > 0.0 and span > fade * 2.05:
                fade_out_st = max(0.0, span - fade)
                af_fade = f",afade=t=in:st=0:d={fade:.2f},afade=t=out:st={fade_out_st:.3f}:d={fade:.2f}"

            a_final: Optional[str] = None
            if audio_clips:
                extra_in, mix_fc, a_final = _build_audio_clips_mix(
                    project_id, audio_clips, next_inp, span, a_cur, af_fade, auto_duck=bool(ae_cfg.get("autoDuck"))
                )
                cmd_mux += extra_in
                fc_mux.extend(mix_fc)
            elif a_cur:
                pad_chain = f"apad=whole_dur={span:.3f},atrim=0:{span:.3f}{af_fade}"
                fc_mux.append(f"{a_cur}{pad_chain}[aout]")
                a_final = "[aout]"

            if fc_mux and a_final:
                cmd_mux += [
                    "-filter_complex",
                    ";".join(fc_mux),
                    "-map",
                    "0:v:0",
                    "-map",
                    a_final,
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                ]
            else:
                cmd_mux += ["-map", "0:v:0", "-an", "-c:v", "copy"]

            cmd_mux += ["-movflags", "+faststart", out_path]
            res_mux = _run_ffmpeg_with_progress(
                cmd_mux, span, progress_cb=None, cancel_ctx=cancel_ctx, timeout=600
            )
            if res_mux.returncode == -2 or (cancel_ev and cancel_ev.is_set()):
                return False, True
            if res_mux.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) < 256:
                return False, False
            if progress_cb is not None:
                progress_cb(99)
            return True, False
    finally:
        if isinstance(cancel_ctx, dict):
            with parent_lock:
                children = cancel_ctx.get("children")
                if isinstance(children, list):
                    try:
                        children.remove(chunk_cancel_ctx)
                    except ValueError:
                        pass


def _export_full_video_clip(
    project_id: str,
    folder: str,
    src_path: str,
    edit_payload: Dict[str, Any],
    progress_cb: Optional[Callable[[int], None]] = None,
    stage_cb: Optional[Callable[[str], None]] = None,
    cancel_ctx: Optional[Dict[str, Any]] = None,
    *,
    clip_id: Optional[str] = None,
    low_priority: bool = False,
    allow_parallel: bool = True,
    attach_prerender: bool = True,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Smart FFmpeg export for Full Video Studio (0s passthrough / prerender handoff / cache / lossless / parallel GPU)."""
    dur, width, height = _probe_video_info(src_path)
    fb_start = max(0.0, float(edit_payload.get("start", 0.0)))
    fb_end = float(edit_payload.get("end", dur or 30.0))
    segments = _sanitize_segments(edit_payload.get("segments"), dur or max(1.0, fb_end), fb_start, fb_end)
    pieces = _expand_segments_to_pieces(segments)
    out_dur = max(0.2, sum((e - s) / spd for s, e, spd, _, _, _ in pieces))

    muted = bool(edit_payload.get("muted", False))
    crop_ratio = _sanitize_crop_ratio(edit_payload.get("cropRatio"))
    fade = _sanitize_fade(edit_payload.get("fade"))
    color_cfg = _sanitize_color(edit_payload.get("color"))
    audio_enhance = _sanitize_audio_enhance(edit_payload.get("audioEnhance"))
    voice_fx = _build_voice_enhance_filters(audio_enhance)

    assets_dir = os.path.join(folder, STUDIO_ASSETS_DIR)
    audio_clips = _sanitize_audio_clips(
        edit_payload.get("audioClips"),
        project_id,
        assets_dir,
        out_dur,
        legacy_music=edit_payload.get("music") if isinstance(edit_payload.get("music"), dict) else None,
    )

    exports_dir = os.path.join(folder, STUDIO_EXPORTS_DIR)
    os.makedirs(exports_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src_path))[0]
    download_name = f"{stem}_studio.mp4"
    out_path = os.path.join(exports_dir, download_name)

    # Smart Render Cache: instant reuse when Export <-> Download is clicked without changing edits
    asset_paths = [
        p for p in (get_studio_music_path(project_id, str(ac.get("assetName") or "")) for ac in audio_clips) if p
    ]
    cache_spec = {
        "pieces": pieces,
        "muted": muted,
        "cropRatio": crop_ratio,
        "fade": fade,
        "color": color_cfg,
        "audioEnhance": audio_enhance,
        "audioClips": [
            {
                "assetName": ac.get("assetName"),
                "timelineStart": ac.get("timelineStart"),
                "trimStart": ac.get("trimStart"),
                "trimEnd": ac.get("trimEnd"),
                "volume": ac.get("volume"),
                "fadeIn": ac.get("fadeIn"),
                "fadeOut": ac.get("fadeOut"),
                "keyframes": ac.get("keyframes"),
            }
            for ac in audio_clips
        ],
    }
    cache_key = _compute_export_cache_key("full_video", src_path, cache_spec, asset_paths)
    crop_filter = _build_crop_filter(crop_ratio, width, height)
    color_filters = _build_color_filters(color_cfg)
    has_speed_fx = any(abs(spd - 1.0) >= 0.01 for _, _, spd, _, _, _ in pieces)
    multi_piece = len(pieces) > 1
    has_vol_change = any(abs(vol - 1.0) >= 0.01 for _, _, _, vol, _, _ in pieces)
    has_src_audio: Optional[bool] = _probe_has_audio(src_path) if (bool(voice_fx) and not muted) else None
    has_voice_enhance = bool(voice_fx) and not muted and bool(has_src_audio)
    has_pixel_fx = bool(crop_filter or color_filters or fade > 0.0 or has_speed_fx)
    has_audio_fx = bool(audio_clips or muted or has_vol_change or has_voice_enhance or fade > 0.0 or has_speed_fx)
    is_mp4_src = os.path.splitext(src_path)[1].lower() == ".mp4"

    # Tier 0: Zero-FFmpeg Instant Passthrough when clip has 0 edits (MP4 source untouched)
    if (
        is_mp4_src
        and not has_pixel_fx
        and not has_audio_fx
        and not multi_piece
        and pieces[0][0] <= 0.05
        and (dur <= 0.1 or pieces[0][1] >= dur - 0.15)
    ):
        if stage_cb:
            stage_cb("Ready")
        if progress_cb:
            progress_cb(99)
        return src_path, os.path.basename(src_path), None

    if _try_reuse_cached_export(out_path, cache_key):
        if stage_cb:
            stage_cb("Using cached render...")
        if progress_cb:
            progress_cb(99)
        return out_path, download_name, None

    # Seamless live handoff: if a background pre-render for this exact edit is already running, attach to it!
    if attach_prerender and clip_id:
        handed_ok, handed_cancelled = _attach_or_cancel_prerender(
            project_id,
            clip_id,
            cache_key,
            out_path,
            progress_cb=progress_cb,
            stage_cb=stage_cb,
            cancel_ctx=cancel_ctx,
        )
        if handed_cancelled:
            return None, None, "Cancelled"
        if handed_ok and os.path.isfile(out_path):
            return out_path, download_name, None

    tmp_out = os.path.join(exports_dir, f"{stem}_studio.{uuid.uuid4().hex[:8]}.tmp.mp4")

    def _cleanup_tmp() -> None:
        if os.path.isfile(tmp_out):
            try:
                os.remove(tmp_out)
            except OSError:
                pass

    def _finalize_tmp() -> Tuple[Optional[str], Optional[str], Optional[str]]:
        if _commit_rendered_export(tmp_out, out_path, cache_key):
            return out_path, download_name, None
        _cleanup_tmp()
        return None, None, "Could not finalize exported video file"

    # Tier 1: Fast Lossless (-c copy) when single 1.0x MP4 block with no pixel/audio effects
    if is_mp4_src and not has_pixel_fx and not has_audio_fx and not multi_piece:
        if stage_cb:
            stage_cb("Copying video...")
        seg_s, seg_e, _, _, _, _ = pieces[0]
        seg_span = max(0.2, seg_e - seg_s)
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{seg_s:.3f}",
            "-t",
            f"{seg_span:.3f}",
            "-i",
            src_path,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            tmp_out,
        ]
        res = _run_ffmpeg_with_progress(
            cmd, seg_span, progress_cb=progress_cb, cancel_ctx=cancel_ctx, timeout=600
        )
        if res.returncode == -2:
            _cleanup_tmp()
            return None, None, "Cancelled"
        if res.returncode == 0 and os.path.isfile(tmp_out):
            return _finalize_tmp()
        _cleanup_tmp()

    if has_src_audio is None:
        has_src_audio = _probe_has_audio(src_path)

    # Tier 1.5: Smart Lossless Multi-Segment Concat (-c copy + concat demuxer)
    # Used when user split/deleted blocks with zero crop/color/fade/speed/music changes.
    if is_mp4_src and not has_pixel_fx and not has_audio_fx and multi_piece:
        if stage_cb:
            stage_cb("Joining clips...")
        ok_cat, cancelled_cat = _concat_segments_lossless(
            src_path,
            pieces,
            tmp_out,
            has_src_audio=has_src_audio,
            muted=False,
            has_vol_change=False,
            progress_cb=progress_cb,
            cancel_ctx=cancel_ctx,
            pct_range=(1, 98),
        )
        if cancelled_cat:
            _cleanup_tmp()
            return None, None, "Cancelled"
        if ok_cat and os.path.isfile(tmp_out):
            return _finalize_tmp()
        _cleanup_tmp()

    # Tier 2: Fast Video Copy (-c:v copy) + Audio Remix when single MP4 block & video pixels are untouched
    if is_mp4_src and not has_pixel_fx and has_audio_fx and not multi_piece:
        if stage_cb:
            stage_cb("Mixing audio...")
        seg_s, seg_e, _, seg_vol, _, _ = pieces[0]
        seg_span = max(0.2, seg_e - seg_s)
        orig_vol = 0.0 if muted else seg_vol
        cmd = ["ffmpeg", "-y", "-ss", f"{seg_s:.3f}", "-t", f"{seg_span:.3f}", "-i", src_path]

        if audio_clips:
            fc_t2: List[str] = []
            a_base_label: Optional[str] = None
            if has_src_audio and not muted and orig_vol > 0.001:
                v_chain = ["asetpts=PTS-STARTPTS", f"volume={orig_vol:.3f}"] + list(voice_fx)
                fc_t2.append(f"[0:a]{','.join(v_chain)}[a0]")
                a_base_label = "[a0]"
            extra_in, mix_fc, a_final_t2 = _build_audio_clips_mix(
                project_id, audio_clips, 1, seg_span, a_base_label, auto_duck=bool(audio_enhance.get("autoDuck"))
            )
            cmd += extra_in
            fc_t2.extend(mix_fc)
            if fc_t2 and a_final_t2:
                cmd += [
                    "-filter_complex",
                    ";".join(fc_t2),
                    "-map",
                    "0:v:0",
                    "-map",
                    a_final_t2,
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                ]
            else:
                cmd += ["-map", "0:v:0", "-an", "-c:v", "copy"]
        elif muted or not has_src_audio or orig_vol <= 0.001:
            cmd += ["-map", "0:v:0", "-an", "-c:v", "copy"]
        else:
            af_t2 = ",".join(["asetpts=PTS-STARTPTS", f"volume={orig_vol:.3f}"] + list(voice_fx))
            cmd += ["-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", af_t2, "-c:a", "aac", "-b:a", "192k"]

        cmd += ["-movflags", "+faststart", tmp_out]
        res = _run_ffmpeg_with_progress(
            cmd, seg_span, progress_cb=progress_cb, cancel_ctx=cancel_ctx, timeout=600
        )
        if res.returncode == -2:
            _cleanup_tmp()
            return None, None, "Cancelled"
        if res.returncode == 0 and os.path.isfile(tmp_out):
            return _finalize_tmp()
        _cleanup_tmp()

    # Tier 2.5: Multi-Segment Lossless Video Copy (-c:v copy) + Audio Mix/Enhance (0 video re-encode!)
    if is_mp4_src and not has_pixel_fx and has_audio_fx and multi_piece:
        if stage_cb:
            stage_cb("Joining clips...")
        if not audio_clips and not has_voice_enhance:
            ok_cat, cancelled_cat = _concat_segments_lossless(
                src_path,
                pieces,
                tmp_out,
                has_src_audio=has_src_audio,
                muted=muted,
                has_vol_change=has_vol_change,
                progress_cb=progress_cb,
                cancel_ctx=cancel_ctx,
                pct_range=(1, 98),
            )
            if cancelled_cat:
                _cleanup_tmp()
                return None, None, "Cancelled"
            if ok_cat and os.path.isfile(tmp_out):
                return _finalize_tmp()
            _cleanup_tmp()
        else:
            with tempfile.TemporaryDirectory(prefix="luna_t25_", ignore_cleanup_errors=True) as td_t25:
                joined_tmp = os.path.join(td_t25, "joined.mp4")
                ok_cat, cancelled_cat = _concat_segments_lossless(
                    src_path,
                    pieces,
                    joined_tmp,
                    has_src_audio=has_src_audio,
                    muted=muted,
                    has_vol_change=has_vol_change,
                    progress_cb=progress_cb,
                    cancel_ctx=cancel_ctx,
                    pct_range=(1, 55),
                )
                if cancelled_cat:
                    _cleanup_tmp()
                    return None, None, "Cancelled"
                if ok_cat and os.path.isfile(joined_tmp):
                    if stage_cb:
                        stage_cb("Mixing audio...")
                    joined_dur, _, _ = _probe_video_info(joined_tmp)
                    mix_dur = joined_dur if joined_dur > 0.2 else out_dur
                    joined_has_audio = _probe_has_audio(joined_tmp) and not muted
                    if audio_clips:
                        fc_t25: List[str] = []
                        a_base_t25: Optional[str] = None
                        if joined_has_audio:
                            if voice_fx:
                                fc_t25.append(f"[0:a:0]{','.join(voice_fx)}[av0]")
                                a_base_t25 = "[av0]"
                            else:
                                a_base_t25 = "[0:a:0]"
                        extra_in, mix_fc, a_final_t25 = _build_audio_clips_mix(
                            project_id,
                            audio_clips,
                            1,
                            mix_dur,
                            a_base_t25,
                            auto_duck=bool(audio_enhance.get("autoDuck")),
                        )
                        fc_t25.extend(mix_fc)
                        if fc_t25 and a_final_t25:
                            cmd_t25 = ["ffmpeg", "-y", "-i", joined_tmp] + extra_in + [
                                "-filter_complex",
                                ";".join(fc_t25),
                                "-map",
                                "0:v:0",
                                "-map",
                                a_final_t25,
                                "-c:v",
                                "copy",
                                "-c:a",
                                "aac",
                                "-b:a",
                                "192k",
                                "-movflags",
                                "+faststart",
                                tmp_out,
                            ]
                        else:
                            cmd_t25 = ["ffmpeg", "-y", "-i", joined_tmp, "-map", "0:v:0", "-an", "-c:v", "copy", "-movflags", "+faststart", tmp_out]
                    elif joined_has_audio:
                        cmd_t25 = [
                            "ffmpeg",
                            "-y",
                            "-i",
                            joined_tmp,
                            "-map",
                            "0:v:0",
                            "-map",
                            "0:a:0",
                            "-c:v",
                            "copy",
                            "-af",
                            ",".join(voice_fx),
                            "-c:a",
                            "aac",
                            "-b:a",
                            "192k",
                            "-movflags",
                            "+faststart",
                            tmp_out,
                        ]
                    else:
                        shutil.copy2(joined_tmp, tmp_out)
                        return _finalize_tmp()

                    def _mix_prog(pct: int) -> None:
                        if progress_cb is not None:
                            progress_cb(min(99, 55 + int((pct / 100.0) * 44)))

                    res_t25 = _run_ffmpeg_with_progress(
                        cmd_t25,
                        mix_dur,
                        progress_cb=_mix_prog if progress_cb else None,
                        cancel_ctx=cancel_ctx,
                        timeout=600,
                    )
                    if res_t25.returncode == -2:
                        _cleanup_tmp()
                        return None, None, "Cancelled"
                    if res_t25.returncode == 0 and os.path.isfile(tmp_out):
                        return _finalize_tmp()
                    _cleanup_tmp()

    # Tier 3: Full Smart Render
    use_src_audio = has_src_audio and not muted
    enc_args = _get_fast_h264_encoder_args()
    needs_even_scale = (not crop_filter) and ((width % 2 != 0) or (height % 2 != 0))
    has_cpu_video_filters = bool(crop_filter or needs_even_scale or color_filters or fade > 0.0)

    # Tier 3A: Parallel Chunk Render for long (>=20s) 1.0x single-segment filtered videos (2-3x faster!)
    if allow_parallel and len(pieces) == 1 and not has_speed_fx and out_dur >= 20.0:
        seg_s, seg_e, _, seg_vol, seg_cx, seg_cy = pieces[0]
        piece_crop = _build_crop_filter(crop_ratio, width, height, seg_cx, seg_cy) if crop_filter else None
        ok_pc, cancelled_pc = _render_tier3_parallel_chunks(
            project_id,
            src_path,
            tmp_out,
            seg_s,
            seg_e,
            seg_vol,
            piece_crop,
            color_filters,
            fade,
            use_src_audio,
            audio_clips,
            enc_args,
            audio_enhance=audio_enhance,
            needs_even_scale=needs_even_scale,
            progress_cb=progress_cb,
            stage_cb=stage_cb,
            cancel_ctx=cancel_ctx,
        )
        if cancelled_pc:
            _cleanup_tmp()
            return None, None, "Cancelled"
        if ok_pc and os.path.isfile(tmp_out):
            return _finalize_tmp()
        _cleanup_tmp()

    # Tier 3B: Single-pass per-group fast input seek (-ss/-t) + smart GPU zero-copy / CPU-filter decode
    if stage_cb:
        stage_cb("Rendering video...")
    groups = _group_pieces_for_fast_seek(pieces)
    hwaccel_args = _get_hwaccel_input_args()
    enc_name = enc_args[1] if len(enc_args) > 1 else "libx264"
    # Zero-copy GPU decode->encode across BOTH AMD (d3d11->h264_amf) and NVIDIA (cuda->h264_nvenc)
    # Only enabled for single-piece clips with no CPU pixel filters (split/trim/concat need CPU frames)
    zero_copy_mode = ""
    can_zero_copy = (
        not has_cpu_video_filters
        and len(pieces) == 1
        and len(groups) == 1
        and len(groups[0]["items"]) == 1
    )
    if can_zero_copy:
        if hwaccel_args == ["-hwaccel", "d3d11va"] and enc_name == "h264_amf":
            zero_copy_mode = "d3d11"
        elif hwaccel_args == ["-hwaccel", "cuda"] and enc_name == "h264_nvenc":
            zero_copy_mode = "cuda"

    def _build_tier3_cmd(use_hw_decode: bool, video_enc_args: List[str], zc_mode: str = "") -> List[str]:
        cmd_built: List[str] = ["ffmpeg", "-y"]
        if zc_mode == "d3d11":
            dec_prefix = ["-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11"]
        elif zc_mode == "cuda":
            dec_prefix = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        elif use_hw_decode:
            dec_prefix = hwaccel_args
        else:
            dec_prefix = []
        for grp in groups:
            g_start = max(0.0, float(grp["start"]))
            g_end = max(g_start + 0.05, float(grp["end"]))
            g_items = grp["items"]
            g_span = (g_end - g_start) + (0.05 if len(g_items) > 1 else 0.0)
            cmd_built += dec_prefix + ["-ss", f"{g_start:.3f}", "-t", f"{g_span:.3f}", "-i", src_path]

        fc_parts: List[str] = []
        concat_inputs: List[str] = []

        for g_idx, grp in enumerate(groups):
            g_start = max(0.0, float(grp["start"]))
            g_items = grp["items"]
            if len(g_items) == 1:
                orig_idx, (_, _, spd, vol, cx, cy) = g_items[0]
                pts_expr = f"(PTS-STARTPTS)/{spd:.4f}" if abs(spd - 1.0) >= 0.01 else "PTS-STARTPTS"
                piece_crop = _build_crop_filter(crop_ratio, width, height, cx, cy) if crop_filter else None
                v_extra = f",{piece_crop}" if piece_crop else ""
                fc_parts.append(f"[{g_idx}:v:0]setpts={pts_expr}{v_extra}[v{orig_idx}]")
                concat_inputs.append(f"[v{orig_idx}]")
                if use_src_audio:
                    atempo = _atempo_chain(spd)
                    a_extra = f",{atempo}" if atempo else ""
                    if abs(vol - 1.0) >= 0.005:
                        a_extra += f",volume={vol:.3f}"
                    fc_parts.append(f"[{g_idx}:a:0]asetpts=PTS-STARTPTS{a_extra}[a{orig_idx}]")
                    concat_inputs.append(f"[a{orig_idx}]")
            else:
                k = len(g_items)
                v_split_labels = "".join(f"[gv{g_idx}_{m}]" for m in range(k))
                fc_parts.append(f"[{g_idx}:v:0]split={k}{v_split_labels}")
                if use_src_audio:
                    a_split_labels = "".join(f"[ga{g_idx}_{m}]" for m in range(k))
                    fc_parts.append(f"[{g_idx}:a:0]asplit={k}{a_split_labels}")
                for m, (orig_idx, (ps, pe, spd, vol, cx, cy)) in enumerate(g_items):
                    rel_ps = max(0.0, ps - g_start)
                    rel_pe = max(rel_ps + 0.05, pe - g_start)
                    pts_expr = f"(PTS-STARTPTS)/{spd:.4f}" if abs(spd - 1.0) >= 0.01 else "PTS-STARTPTS"
                    piece_crop = _build_crop_filter(crop_ratio, width, height, cx, cy) if crop_filter else None
                    v_extra = f",{piece_crop}" if piece_crop else ""
                    fc_parts.append(
                        f"[gv{g_idx}_{m}]trim=start={rel_ps:.3f}:end={rel_pe:.3f},setpts={pts_expr}{v_extra}[v{orig_idx}]"
                    )
                    concat_inputs.append(f"[v{orig_idx}]")
                    if use_src_audio:
                        atempo = _atempo_chain(spd)
                        a_extra = f",{atempo}" if atempo else ""
                        if abs(vol - 1.0) >= 0.005:
                            a_extra += f",volume={vol:.3f}"
                        fc_parts.append(
                            f"[ga{g_idx}_{m}]atrim=start={rel_ps:.3f}:end={rel_pe:.3f},asetpts=PTS-STARTPTS{a_extra}[a{orig_idx}]"
                        )
                        concat_inputs.append(f"[a{orig_idx}]")

        if len(pieces) == 1:
            v_cur = "[v0]"
            a_cur = "[a0]" if use_src_audio else None
        else:
            a_out_flag = 1 if use_src_audio else 0
            out_labels = "[vcat][acat]" if use_src_audio else "[vcat]"
            fc_parts.append(f"{''.join(concat_inputs)}concat=n={len(pieces)}:v=1:a={a_out_flag}{out_labels}")
            v_cur = "[vcat]"
            a_cur = "[acat]" if use_src_audio else None

        vf_chain: List[str] = []
        if needs_even_scale:
            vf_chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
        vf_chain.extend(color_filters)
        if fade > 0.0 and out_dur > fade * 2.05:
            fade_out_st = max(0.0, out_dur - fade)
            vf_chain.append(f"fade=t=in:st=0:d={fade:.2f}")
            vf_chain.append(f"fade=t=out:st={fade_out_st:.3f}:d={fade:.2f}")
        if vf_chain:
            fc_parts.append(f"{v_cur}{','.join(vf_chain)}[vout]")
            v_final = "[vout]"
        else:
            v_final = v_cur

        if a_cur and voice_fx:
            fc_parts.append(f"{a_cur}{','.join(voice_fx)}[avfx]")
            a_cur = "[avfx]"

        a_final: Optional[str] = None
        af_fade = ""
        if fade > 0.0 and out_dur > fade * 2.05:
            fade_out_st = max(0.0, out_dur - fade)
            af_fade = f",afade=t=in:st=0:d={fade:.2f},afade=t=out:st={fade_out_st:.3f}:d={fade:.2f}"

        if audio_clips:
            extra_in, mix_fc, a_final = _build_audio_clips_mix(
                project_id,
                audio_clips,
                len(groups),
                out_dur,
                a_cur,
                af_fade,
                auto_duck=bool(audio_enhance.get("autoDuck")),
            )
            cmd_built += extra_in
            fc_parts.extend(mix_fc)
        elif a_cur:
            if af_fade:
                fc_parts.append(f"{a_cur}{af_fade.lstrip(',')}[aout]")
                a_final = "[aout]"
            else:
                a_final = a_cur

        cmd_built += ["-filter_complex", ";".join(fc_parts), "-map", v_final]
        if a_final:
            cmd_built += ["-map", a_final, "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd_built += ["-an"]

        effective_enc = list(video_enc_args)
        if zc_mode:
            # Strip -pix_fmt yuv420p so frames remain in native GPU VRAM surfaces
            filtered_enc: List[str] = []
            skip_next = False
            for tok in effective_enc:
                if skip_next:
                    skip_next = False
                    continue
                if tok == "-pix_fmt":
                    skip_next = True
                    continue
                filtered_enc.append(tok)
            effective_enc = filtered_enc

        cmd_built += effective_enc + ["-movflags", "+faststart", tmp_out]
        return cmd_built

    # Skip VRAM download overhead when CPU pixel filters are active (direct CPU yuv420p decode is faster)
    use_hw_dec_now = bool(hwaccel_args) and not has_cpu_video_filters
    used_hw = use_hw_dec_now or bool(zero_copy_mode) or enc_args[1] != "libx264"
    cmd_hw = _build_tier3_cmd(
        use_hw_decode=use_hw_dec_now, video_enc_args=enc_args, zc_mode=zero_copy_mode
    )
    res = _run_ffmpeg_with_progress(
        cmd_hw, out_dur, progress_cb=progress_cb, cancel_ctx=cancel_ctx, timeout=1800, low_priority=low_priority
    )
    if res.returncode == -2:
        _cleanup_tmp()
        return None, None, "Cancelled"
    # Intermediate fallback: if GPU zero-copy or HW decode failed, retry CPU-decode + GPU-encode before falling back to CPU libx264
    if (res.returncode != 0 or not os.path.isfile(tmp_out)) and (use_hw_dec_now or zero_copy_mode) and enc_name != "libx264":
        _cleanup_tmp()
        cmd_gpu_only = _build_tier3_cmd(use_hw_decode=False, video_enc_args=enc_args, zc_mode="")
        res = _run_ffmpeg_with_progress(
            cmd_gpu_only, out_dur, progress_cb=progress_cb, cancel_ctx=cancel_ctx, timeout=1800, low_priority=low_priority
        )
        if res.returncode == -2:
            _cleanup_tmp()
            return None, None, "Cancelled"
    if (res.returncode != 0 or not os.path.isfile(tmp_out)) and used_hw:
        _cleanup_tmp()
        sw_enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "0", "-pix_fmt", "yuv420p"]
        cmd_sw = _build_tier3_cmd(use_hw_decode=False, video_enc_args=sw_enc, zc_mode="")
        res = _run_ffmpeg_with_progress(
            cmd_sw, out_dur, progress_cb=progress_cb, cancel_ctx=cancel_ctx, timeout=1800, low_priority=low_priority
        )
        if res.returncode == -2:
            _cleanup_tmp()
            return None, None, "Cancelled"
    if res.returncode != 0 or not os.path.isfile(tmp_out):
        _cleanup_tmp()
        err_tail = (res.stderr or res.stdout or "FFmpeg render failed").strip()[-350:]
        return None, None, f"Render failed: {err_tail}"
    return _finalize_tmp()


def get_studio_export_path(project_id: str, filename: str) -> Optional[str]:
    """Safely resolve a rendered file inside ``studio_exports/`` or an untouched source video in the project folder."""
    found = find_studio_project(project_id)
    if not found:
        return None
    _, folder = found
    safe_name = os.path.basename(str(filename or ""))
    if not safe_name or safe_name in (".", ".."):
        return None
    exports_dir = os.path.realpath(os.path.join(folder, STUDIO_EXPORTS_DIR))
    candidate = os.path.realpath(os.path.join(exports_dir, safe_name))
    try:
        if os.path.commonpath([exports_dir, candidate]) == exports_dir and os.path.isfile(candidate):
            return candidate
    except ValueError:
        pass
    # Tier 0 zero-FFmpeg direct download: allow streaming an untouched source video from the project folder
    ext = os.path.splitext(safe_name)[1].lower()
    if ext in VIDEO_FILE_EXTS:
        real_folder = os.path.realpath(folder)
        direct = os.path.realpath(os.path.join(real_folder, safe_name))
        try:
            if os.path.commonpath([real_folder, direct]) == real_folder and os.path.isfile(direct):
                return direct
        except ValueError:
            pass
    return None


def extract_studio_audio(
    project_id: str, clip_id: str, edit_payload: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract 320 kbps MP3 from the active timeline blocks (optionally mixed with background music)."""
    if not ffmpeg_setup.ensure_ffmpeg():
        return None, None, "FFmpeg is not available on this system"

    _, folder, _, src_path, err = _resolve_project_clip(project_id, clip_id)
    if err or not folder or not src_path:
        return None, None, err or "Clip not found"

    dur, _, _ = _probe_video_info(src_path)
    fb_start = max(0.0, float(edit_payload.get("start", 0.0)))
    fb_end = float(edit_payload.get("end", dur or 30.0))
    segments = _sanitize_segments(edit_payload.get("segments"), dur or max(1.0, fb_end), fb_start, fb_end)
    pieces = _expand_segments_to_pieces(segments)
    out_dur = max(0.2, sum((e - s) / spd for s, e, spd, _, _, _ in pieces))

    muted = bool(edit_payload.get("muted", False))
    fade = _sanitize_fade(edit_payload.get("fade"))
    audio_enhance = _sanitize_audio_enhance(edit_payload.get("audioEnhance"))
    voice_fx = _build_voice_enhance_filters(audio_enhance)

    assets_dir = os.path.join(folder, STUDIO_ASSETS_DIR)
    audio_clips = _sanitize_audio_clips(
        edit_payload.get("audioClips"),
        project_id,
        assets_dir,
        out_dur,
        legacy_music=edit_payload.get("music") if isinstance(edit_payload.get("music"), dict) else None,
    )

    has_src_audio = _probe_has_audio(src_path)
    use_src_audio = has_src_audio and not muted
    if not use_src_audio and not audio_clips:
        return None, None, "No active audio track to extract (unmute Original or add Music)"

    exports_dir = os.path.join(folder, STUDIO_EXPORTS_DIR)
    os.makedirs(exports_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src_path))[0]
    download_name = f"{stem}_audio.mp3"
    out_path = os.path.join(exports_dir, download_name)
    tmp_mp3 = os.path.join(exports_dir, f"{stem}_audio.{uuid.uuid4().hex[:8]}.tmp.mp3")

    cmd: List[str] = ["ffmpeg", "-y"]
    fc_parts: List[str] = []
    a_cur: Optional[str] = None
    next_inp_idx = 0
    if use_src_audio:
        groups = _group_pieces_for_fast_seek(pieces)
        a_inputs: List[str] = []
        for g_idx, grp in enumerate(groups):
            g_start = max(0.0, float(grp["start"]))
            g_end = max(g_start + 0.05, float(grp["end"]))
            g_items = grp["items"]
            g_span = (g_end - g_start) + (0.05 if len(g_items) > 1 else 0.0)
            # -vn skips video decoding completely during MP3 extraction
            cmd += ["-vn", "-ss", f"{g_start:.3f}", "-t", f"{g_span:.3f}", "-i", src_path]
            if len(g_items) == 1:
                orig_idx, (_, _, spd, vol, _, _) = g_items[0]
                atempo = _atempo_chain(spd)
                a_extra = f",{atempo}" if atempo else ""
                if abs(vol - 1.0) >= 0.005:
                    a_extra += f",volume={vol:.3f}"
                fc_parts.append(f"[{g_idx}:a:0]asetpts=PTS-STARTPTS{a_extra}[a{orig_idx}]")
                a_inputs.append(f"[a{orig_idx}]")
            else:
                k = len(g_items)
                a_split_labels = "".join(f"[ga{g_idx}_{m}]" for m in range(k))
                fc_parts.append(f"[{g_idx}:a:0]asplit={k}{a_split_labels}")
                for m, (orig_idx, (ps, pe, spd, vol, _, _)) in enumerate(g_items):
                    rel_ps = max(0.0, ps - g_start)
                    rel_pe = max(rel_ps + 0.05, pe - g_start)
                    atempo = _atempo_chain(spd)
                    a_extra = f",{atempo}" if atempo else ""
                    if abs(vol - 1.0) >= 0.005:
                        a_extra += f",volume={vol:.3f}"
                    fc_parts.append(
                        f"[ga{g_idx}_{m}]atrim=start={rel_ps:.3f}:end={rel_pe:.3f},asetpts=PTS-STARTPTS{a_extra}[a{orig_idx}]"
                    )
                    a_inputs.append(f"[a{orig_idx}]")
        next_inp_idx = len(groups)
        if len(pieces) == 1:
            a_cur = "[a0]"
        else:
            fc_parts.append(f"{''.join(a_inputs)}concat=n={len(pieces)}:v=0:a=1[acat]")
            a_cur = "[acat]"

    if a_cur and voice_fx:
        fc_parts.append(f"{a_cur}{','.join(voice_fx)}[avfx]")
        a_cur = "[avfx]"

    af_fade = ""
    if fade > 0.0 and out_dur > fade * 2.05:
        fade_out_st = max(0.0, out_dur - fade)
        af_fade = f",afade=t=in:st=0:d={fade:.2f},afade=t=out:st={fade_out_st:.3f}:d={fade:.2f}"

    a_final: Optional[str] = None
    if audio_clips:
        extra_in, mix_fc, a_final = _build_audio_clips_mix(
            project_id,
            audio_clips,
            next_inp_idx,
            out_dur,
            a_cur,
            af_fade,
            auto_duck=bool(audio_enhance.get("autoDuck")),
        )
        cmd += extra_in
        fc_parts.extend(mix_fc)
    elif a_cur:
        if af_fade:
            fc_parts.append(f"{a_cur}{af_fade.lstrip(',')}[aout]")
        else:
            fc_parts.append(f"{a_cur}anull[aout]")
        a_final = "[aout]"

    if not fc_parts or not a_final:
        return None, None, "No active audio track to extract (unmute Original or add Music)"

    cmd += ["-filter_complex", ";".join(fc_parts), "-map", a_final, "-vn", "-c:a", "libmp3lame", "-b:a", "320k", tmp_mp3]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    except subprocess.TimeoutExpired:
        if os.path.exists(tmp_mp3):
            try:
                os.remove(tmp_mp3)
            except OSError:
                pass
        return None, None, "Audio extraction timed out"
    if res.returncode != 0 or not os.path.isfile(tmp_mp3):
        if os.path.exists(tmp_mp3):
            try:
                os.remove(tmp_mp3)
            except OSError:
                pass
        err_tail = (res.stderr or res.stdout or "Audio extraction failed").strip()[-350:]
        return None, None, f"Audio extraction failed: {err_tail}"
    try:
        with _get_export_file_lock(out_path):
            os.replace(tmp_mp3, out_path)
    except OSError:
        if os.path.exists(tmp_mp3):
            try:
                os.remove(tmp_mp3)
            except OSError:
                pass
        return None, None, "Could not finalize extracted audio file"
    return out_path, download_name, None


def export_studio_clip(
    project_id: str,
    clip_id: str,
    edit_payload: Dict[str, Any],
    progress_cb: Optional[Callable[[int], None]] = None,
    stage_cb: Optional[Callable[[str], None]] = None,
    cancel_ctx: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Render an edited MP4 into ``studio_exports/`` without touching the original clip."""
    if not ffmpeg_setup.ensure_ffmpeg():
        return None, None, "FFmpeg is not available on this system"

    proj, folder, _, src_path, err = _resolve_project_clip(project_id, clip_id)
    if err or not proj or not folder or not src_path:
        return None, None, err or "Clip not found"

    if get_studio_mode(proj) == "full_video":
        return _export_full_video_clip(
            project_id,
            folder,
            src_path,
            edit_payload,
            progress_cb=progress_cb,
            stage_cb=stage_cb,
            cancel_ctx=cancel_ctx,
            clip_id=clip_id,
        )

    dur, width, height = _probe_video_info(src_path)
    trim_start = max(0.0, float(edit_payload.get("start", 0.0)))
    trim_end = float(edit_payload.get("end", dur or 30.0))
    if dur > 0.2:
        trim_end = min(dur, max(trim_start + 0.5, trim_end))
    clip_span = max(0.5, trim_end - trim_start)

    muted = bool(edit_payload.get("muted", False))
    sub_style = str(edit_payload.get("subStyle") or "none")
    sub_size = str(edit_payload.get("subSize") or "medium")
    custom_scale = max(45, min(200, int(edit_payload.get("customScale", 100))))
    if sub_size == "small":
        size_scale = 0.8
    elif sub_size == "large":
        size_scale = 1.24
    elif sub_size == "custom":
        size_scale = custom_scale / 100.0
    else:
        size_scale = 1.0

    sub_pos = str(edit_payload.get("subPos") or "bottom")
    pos_x = 50.0
    pos_y = 78.0
    if sub_pos == "top":
        pos_y = 18.0
    elif sub_pos == "middle":
        pos_y = 50.0
    elif sub_pos == "custom":
        pos_x = max(15.0, min(85.0, float(edit_payload.get("posX", 50.0))))
        pos_y = max(10.0, min(92.0, float(edit_payload.get("posY", 78.0))))

    cues = edit_payload.get("cues") if isinstance(edit_payload.get("cues"), list) else []

    music_path = None
    music_slice_start = 0.0
    music_vol = 0.35
    music_cfg = edit_payload.get("music")
    if isinstance(music_cfg, dict) and music_cfg.get("assetName"):
        music_path = get_studio_music_path(project_id, str(music_cfg["assetName"]))
        if music_path:
            music_slice_start = _resolve_music_slice_start(
                music_path, float(music_cfg.get("sliceStart") or 0.0), clip_span
            )
        music_vol = max(0.0, min(1.0, float(music_cfg.get("volume", 35)) / 100.0))

    exports_dir = os.path.join(folder, STUDIO_EXPORTS_DIR)
    os.makedirs(exports_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src_path))[0]
    download_name = f"{stem}_studio.mp4"
    out_path = os.path.join(exports_dir, download_name)

    ai_cache_key = _compute_export_cache_key(
        "ai_clip",
        src_path,
        {
            "trim_start": round(trim_start, 3),
            "trim_end": round(trim_end, 3),
            "muted": muted,
            "sub_style": sub_style,
            "size_scale": size_scale,
            "pos_x": pos_x,
            "pos_y": pos_y,
            "cues": cues if sub_style == "selene" else [],
            "music_slice_start": round(music_slice_start, 3),
            "music_vol": round(music_vol, 3),
        },
        [music_path] if music_path else [],
    )
    if _try_reuse_cached_export(out_path, ai_cache_key):
        if stage_cb:
            stage_cb("Using cached render...")
        if progress_cb:
            progress_cb(99)
        return out_path, download_name, None

    ass_tmp: Optional[str] = None
    try:
        vf_parts: List[str] = []
        if sub_style == "selene" and cues:
            ass_content = _build_selene_ass(cues, trim_start, trim_end, width, height, size_scale, pos_x, pos_y)
            fd, ass_tmp = tempfile.mkstemp(prefix="luna_studio_", suffix=".ass")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(ass_content)
            vf_parts.append(f"ass='{_escape_ffmpeg_filter_path(ass_tmp)}'")
        if (width % 2 != 0) or (height % 2 != 0):
            vf_parts.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")

        hwaccel_args = _get_hwaccel_input_args()
        enc_args = _get_fast_h264_encoder_args()

        tmp_out = os.path.join(exports_dir, f"{stem}_studio.{uuid.uuid4().hex[:8]}.tmp.mp4")

        def _cleanup_ai_tmp() -> None:
            if os.path.isfile(tmp_out):
                try:
                    os.remove(tmp_out)
                except OSError:
                    pass

        def _build_ai_clip_cmd(use_hw_decode: bool, video_enc_args: List[str]) -> List[str]:
            cmd_built: List[str] = ["ffmpeg", "-y"]
            if use_hw_decode:
                cmd_built += hwaccel_args
            cmd_built += ["-ss", f"{trim_start:.3f}", "-t", f"{clip_span:.3f}", "-i", src_path]
            if music_path:
                cmd_built += ["-stream_loop", "-1", "-ss", f"{music_slice_start:.3f}", "-t", f"{clip_span:.3f}", "-i", music_path]

            if music_path:
                fc_parts: List[str] = []
                if vf_parts:
                    fc_parts.append(f"[0:v:0]{','.join(vf_parts)}[vout]")
                    v_map = "[vout]"
                else:
                    v_map = "0:v:0"

                if muted:
                    fc_parts.append(f"[1:a]volume={music_vol:.3f}[aout]")
                else:
                    fc_parts.append(
                        f"[0:a]volume=1.0[a0];[1:a]volume={music_vol:.3f}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]"
                    )
                cmd_built += ["-filter_complex", ";".join(fc_parts), "-map", v_map, "-map", "[aout]"]
            else:
                if vf_parts:
                    cmd_built += ["-vf", ",".join(vf_parts)]
                if muted:
                    cmd_built += ["-map", "0:v:0", "-an"]
                else:
                    cmd_built += ["-map", "0:v:0", "-map", "0:a?"]

            cmd_built += video_enc_args + [
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                tmp_out,
            ]
            return cmd_built

        if stage_cb:
            stage_cb("Rendering clip...")
        used_hw = bool(hwaccel_args) or enc_args[1] != "libx264"
        cmd_hw = _build_ai_clip_cmd(use_hw_decode=bool(hwaccel_args), video_enc_args=enc_args)
        res = _run_ffmpeg_with_progress(
            cmd_hw, clip_span, progress_cb=progress_cb, cancel_ctx=cancel_ctx, timeout=600
        )
        if res.returncode == -2:
            _cleanup_ai_tmp()
            return None, None, "Cancelled"
        if (res.returncode != 0 or not os.path.isfile(tmp_out)) and bool(hwaccel_args) and enc_args[1] != "libx264":
            _cleanup_ai_tmp()
            cmd_gpu_only = _build_ai_clip_cmd(use_hw_decode=False, video_enc_args=enc_args)
            res = _run_ffmpeg_with_progress(
                cmd_gpu_only, clip_span, progress_cb=progress_cb, cancel_ctx=cancel_ctx, timeout=600
            )
            if res.returncode == -2:
                _cleanup_ai_tmp()
                return None, None, "Cancelled"
        if (res.returncode != 0 or not os.path.isfile(tmp_out)) and used_hw:
            _cleanup_ai_tmp()
            sw_enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "0", "-pix_fmt", "yuv420p"]
            cmd_sw = _build_ai_clip_cmd(use_hw_decode=False, video_enc_args=sw_enc)
            res = _run_ffmpeg_with_progress(
                cmd_sw, clip_span, progress_cb=progress_cb, cancel_ctx=cancel_ctx, timeout=600
            )
            if res.returncode == -2:
                _cleanup_ai_tmp()
                return None, None, "Cancelled"
        if res.returncode != 0 or not os.path.isfile(tmp_out):
            _cleanup_ai_tmp()
            err_tail = (res.stderr or res.stdout or "FFmpeg render failed").strip()[-350:]
            return None, None, f"Render failed: {err_tail}"
        if not _commit_rendered_export(tmp_out, out_path, ai_cache_key):
            _cleanup_ai_tmp()
            return None, None, "Could not finalize rendered clip"
        return out_path, download_name, None
    finally:
        if ass_tmp and os.path.exists(ass_tmp):
            try:
                os.remove(ass_tmp)
            except OSError:
                pass


def _infer_aspect_ratio_label(width: int, height: int, crop_ratio: Optional[str] = None) -> str:
    if crop_ratio in ("16:9", "9:16", "1:1", "3:4"):
        return crop_ratio
    if width <= 0 or height <= 0:
        return "16:9"
    r = width / float(height)
    candidates = [("16:9", 16 / 9), ("9:16", 9 / 16), ("1:1", 1.0), ("3:4", 3 / 4), ("4:3", 4 / 3)]
    best_lbl, best_diff = min(((lbl, abs(r - val)) for lbl, val in candidates), key=lambda x: x[1])
    if best_diff <= 0.08:
        return best_lbl
    return f"{width}:{height}"


_WORKSPACE_FOLDER_LOCKS_GUARD = threading.Lock()
_WORKSPACE_FOLDER_LOCKS: Dict[str, threading.Lock] = {}


def _get_workspace_folder_lock(folder: str) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(folder))
    with _WORKSPACE_FOLDER_LOCKS_GUARD:
        lock = _WORKSPACE_FOLDER_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _WORKSPACE_FOLDER_LOCKS[key] = lock
        return lock


def _append_workspace_file_record(
    folder: str, project_id: str, proj: Dict[str, Any], file_record: Dict[str, Any]
) -> None:
    """Append an exported video file record into the workspace's meta.json atomically."""
    meta_path = os.path.join(folder, vault_service.INDEX_FILE_NAME)
    with _get_workspace_folder_lock(folder):
        loaded: Any = None
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except Exception:
                loaded = None

        if isinstance(loaded, list):
            for entry in loaded:
                if isinstance(entry, dict) and entry.get("project_id") == project_id:
                    files = entry.get("files")
                    if not isinstance(files, list):
                        files = []
                        entry["files"] = files
                    files.append(file_record)
                    vault_service._atomic_write_json(meta_path, loaded)
                    return
            # Legacy flat list of file records in meta.json
            if loaded and all(isinstance(e, dict) and not e.get("project_id") for e in loaded):
                loaded.append(file_record)
                vault_service._atomic_write_json(meta_path, loaded)
                return

        if isinstance(loaded, dict) and loaded.get("project_id") == project_id:
            files = loaded.get("files")
            if not isinstance(files, list):
                files = []
                loaded["files"] = files
            files.append(file_record)
            vault_service._atomic_write_json(meta_path, loaded)
            return

        # Fallback: persist updated project copy via vault_service
        updated_proj = dict(proj)
        existing_files = list(proj.get("files") or [])
        existing_files.append(file_record)
        updated_proj["files"] = existing_files
        updated_proj.pop("virtual", None)
        vault_service.save_project_metadata(folder, updated_proj)


def export_studio_clip_to_workspace(
    project_id: str,
    clip_id: str,
    edit_payload: Dict[str, Any],
    progress_cb: Optional[Callable[[int], None]] = None,
    stage_cb: Optional[Callable[[str], None]] = None,
    cancel_ctx: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Render an edited MP4 and save it as a new video inside the project's Vault workspace."""
    proj, folder, clip_rec, src_path, err = _resolve_project_clip(project_id, clip_id)
    if err or not proj or not folder or not clip_rec or not src_path:
        return None, err or "Clip not found"

    out_path, _, render_err = export_studio_clip(
        project_id,
        clip_id,
        edit_payload,
        progress_cb=progress_cb,
        stage_cb=stage_cb,
        cancel_ctx=cancel_ctx,
    )
    if render_err or not out_path or not os.path.isfile(out_path):
        return None, render_err or "Export failed"

    cancel_ev: Optional[threading.Event] = cancel_ctx.get("event") if isinstance(cancel_ctx, dict) else None
    if cancel_ev and cancel_ev.is_set():
        return None, "Cancelled"

    if stage_cb:
        stage_cb("Saving to workspace...")

    raw_stem = os.path.splitext(os.path.basename(src_path))[0]
    base_stem = re.sub(r"(?:_edited(?:_\d+)?|_studio)$", "", raw_stem, flags=re.IGNORECASE).strip() or raw_stem
    src_title = str(clip_rec.get("title") or base_stem).strip()
    clean_title = re.sub(r"\s*\(Edited(?:\s+\d+)?\)$", "", src_title, flags=re.IGNORECASE).strip() or base_stem

    with _get_workspace_folder_lock(folder):
        if cancel_ev and cancel_ev.is_set():
            return None, "Cancelled"
        counter = 1
        dst_filename = f"{base_stem}_edited.mp4"
        dst_path = os.path.join(folder, dst_filename)
        while os.path.exists(dst_path):
            counter += 1
            dst_filename = f"{base_stem}_edited_{counter}.mp4"
            dst_path = os.path.join(folder, dst_filename)
        # Reserve the unique filename atomically while holding the folder lock
        with open(dst_path, "wb"):
            pass

    cover_dst: Optional[str] = None
    try:
        shutil.copy2(out_path, dst_path)
        if cancel_ev and cancel_ev.is_set():
            raise RuntimeError("Cancelled")

        _, src_w, src_h = _probe_video_info(src_path)
        out_dur, out_w, out_h = _probe_video_info(dst_path)
        storage_root = storage_manager.get_storage_root()
        try:
            rel_video = os.path.relpath(os.path.abspath(dst_path), os.path.abspath(storage_root)).replace("\\", "/")
        except ValueError:
            rel_video = dst_filename

        display_title = f"{clean_title} (Edited)" if counter == 1 else f"{clean_title} (Edited {counter})"
        aspect_label = _infer_aspect_ratio_label(out_w, out_h, edit_payload.get("cropRatio"))
        quality_label = _infer_quality_label(out_w, out_h, src_w, src_h, clip_rec.get("quality"))

        file_id = f"f_{uuid.uuid4().hex[:8]}"
        file_record: Dict[str, Any] = {
            "id": file_id,
            "title": display_title,
            "filename": dst_filename,
            "file_path": os.path.abspath(dst_path),
            "url": f"/media-vault/{quote(rel_video, safe='/')}",
            "file_size": os.path.getsize(dst_path),
            "type": "video",
            "platform": proj.get("platform") or "youtube",
            "action": proj.get("action") or "type_yt_video",
            "duration": round(out_dur, 2) if out_dur > 0 else 0,
            "aspect_ratio": aspect_label,
            "edited_in_studio": True,
            "created_at": time.time(),
        }
        if quality_label:
            file_record["quality"] = quality_label

        # Best-effort cover thumbnail for Vault card preview
        try:
            covers_dir = os.path.join(folder, "covers")
            os.makedirs(covers_dir, exist_ok=True)
            cover_fname = f"{os.path.splitext(dst_filename)[0]}.jpg"
            cover_dst = os.path.join(covers_dir, cover_fname)
            grab_sec = min(1.0, max(0.0, out_dur * 0.25)) if out_dur > 0.2 else 0.0
            thumb_res = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{grab_sec:.2f}",
                    "-i",
                    dst_path,
                    "-vframes",
                    "1",
                    "-q:v",
                    "3",
                    cover_dst,
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if thumb_res.returncode == 0 and os.path.isfile(cover_dst):
                cover_rel = os.path.relpath(os.path.abspath(cover_dst), os.path.abspath(storage_root)).replace("\\", "/")
                file_record["thumbnail"] = f"/media-vault/{quote(cover_rel, safe='/')}"
                file_record["thumbnail_path"] = os.path.abspath(cover_dst)
        except Exception:
            pass

        if cancel_ev and cancel_ev.is_set():
            raise RuntimeError("Cancelled")

        _append_workspace_file_record(folder, project_id, proj, file_record)
    except RuntimeError as exc:
        if str(exc) == "Cancelled":
            for p_clean in (dst_path, cover_dst):
                if p_clean and os.path.isfile(p_clean):
                    try:
                        os.remove(p_clean)
                    except OSError:
                        pass
            return None, "Cancelled"
        raise

    new_dur = round(out_dur, 3) if out_dur > 0.1 else 1.0
    studio_clip = {
        "id": file_id,
        "name": display_title,
        "filename": dst_filename,
        "src": file_record["url"],
        "dur": new_dur,
        "start": 0.0,
        "end": new_dur,
        "title": display_title,
        "tags": "",
        "caption": "",
        "cues": [],
        "music": None,
        "audioClips": [],
        "audioEnhance": {"normalize": False, "denoise": False, "autoDuck": False},
        "cropRatio": "original",
        "fade": 0,
        "color": {
            "preset": "natural",
            "brightness": 0,
            "contrast": 0,
            "saturation": 0,
            "exposure": 0,
            "warmth": 0,
            "sharpness": 0,
            "vignette": 0,
        },
        "segments": [
            {
                "id": "seg_1",
                "sourceStart": 0.0,
                "sourceEnd": new_dur,
                "volume": 100,
                "speedMode": "normal",
                "speed": 1.0,
                "curvePreset": "none",
                "curvePoints": [1.0, 1.0, 1.0, 1.0, 1.0],
                "curvePositions": [0.0, 0.25, 0.5, 0.75, 1.0],
                "cropX": 50.0,
                "cropY": 50.0,
            }
        ],
    }
    return {"ok": True, "file": file_record, "clip": studio_clip}, None


_STUDIO_JOBS_LOCK = threading.Lock()
_STUDIO_JOBS: Dict[str, Dict[str, Any]] = {}
_STUDIO_JOB_CANCELS: Dict[str, Dict[str, Any]] = {}


def _prune_old_studio_jobs() -> None:
    now = time.time()
    stale = [
        jid
        for jid, rec in _STUDIO_JOBS.items()
        if rec.get("status") in ("done", "error", "cancelled") and (now - float(rec.get("updated_at") or 0)) > 600
    ]
    for jid in stale:
        _STUDIO_JOBS.pop(jid, None)
        _STUDIO_JOB_CANCELS.pop(jid, None)


def start_studio_render_job(
    project_id: str, clip_id: str, mode: str, edit_payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Start a background FFmpeg render job ('download' or 'workspace') with real-time progress & cancel."""
    norm_mode = "workspace" if mode == "workspace" else "download"
    job_id = f"stj_{uuid.uuid4().hex[:10]}"
    now = time.time()
    cancel_ctx: Dict[str, Any] = {"event": threading.Event(), "proc": None, "procs": set()}
    job_rec: Dict[str, Any] = {
        "id": job_id,
        "project_id": project_id,
        "clip_id": clip_id,
        "mode": norm_mode,
        "status": "running",
        "stage": "Preparing...",
        "progress": 0,
        "filename": None,
        "downloadUrl": None,
        "file": None,
        "clip": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    with _STUDIO_JOBS_LOCK:
        _prune_old_studio_jobs()
        _STUDIO_JOBS[job_id] = job_rec
        _STUDIO_JOB_CANCELS[job_id] = cancel_ctx

    def _on_progress(pct: int) -> None:
        with _STUDIO_JOBS_LOCK:
            rec = _STUDIO_JOBS.get(job_id)
            if rec and rec["status"] == "running":
                rec["progress"] = max(int(rec["progress"] or 0), min(99, int(pct)))
                rec["updated_at"] = time.time()

    def _on_stage(stage_label: str) -> None:
        with _STUDIO_JOBS_LOCK:
            rec = _STUDIO_JOBS.get(job_id)
            if rec and rec["status"] == "running":
                rec["stage"] = str(stage_label or "")
                rec["updated_at"] = time.time()

    def _worker() -> None:
        try:
            if norm_mode == "workspace":
                result, err = export_studio_clip_to_workspace(
                    project_id,
                    clip_id,
                    edit_payload,
                    progress_cb=_on_progress,
                    stage_cb=_on_stage,
                    cancel_ctx=cancel_ctx,
                )
                with _STUDIO_JOBS_LOCK:
                    rec = _STUDIO_JOBS.get(job_id)
                    if not rec:
                        return
                    if cancel_ctx["event"].is_set() or err == "Cancelled":
                        rec["status"] = "cancelled"
                        rec["stage"] = "Cancelled"
                        rec["error"] = "Cancelled"
                    elif err or not result:
                        rec["status"] = "error"
                        rec["error"] = err or "Export failed"
                    else:
                        rec["status"] = "done"
                        rec["stage"] = "Done"
                        rec["progress"] = 100
                        rec["file"] = result.get("file")
                        rec["clip"] = result.get("clip")
                        rec["filename"] = (result.get("file") or {}).get("filename")
                    rec["updated_at"] = time.time()
            else:
                out_path, download_name, err = export_studio_clip(
                    project_id,
                    clip_id,
                    edit_payload,
                    progress_cb=_on_progress,
                    stage_cb=_on_stage,
                    cancel_ctx=cancel_ctx,
                )
                with _STUDIO_JOBS_LOCK:
                    rec = _STUDIO_JOBS.get(job_id)
                    if not rec:
                        return
                    if cancel_ctx["event"].is_set() or err == "Cancelled":
                        rec["status"] = "cancelled"
                        rec["stage"] = "Cancelled"
                        rec["error"] = "Cancelled"
                    elif err or not out_path or not download_name:
                        rec["status"] = "error"
                        rec["error"] = err or "Download failed"
                    else:
                        rec["status"] = "done"
                        rec["stage"] = "Done"
                        rec["progress"] = 100
                        rec["filename"] = download_name
                        rec["downloadUrl"] = (
                            f"/api/studio/{quote(project_id, safe='')}/download-export/{quote(download_name, safe='')}"
                        )
                    rec["updated_at"] = time.time()
        except Exception as exc:
            with _STUDIO_JOBS_LOCK:
                rec = _STUDIO_JOBS.get(job_id)
                if rec:
                    rec["status"] = "cancelled" if cancel_ctx["event"].is_set() else "error"
                    rec["error"] = "Cancelled" if cancel_ctx["event"].is_set() else (str(exc) or "Render failed")
                    rec["updated_at"] = time.time()

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "jobId": job_id}


def cancel_studio_render_job(job_id: str) -> bool:
    """Cancel an active Studio render job and immediately terminate its FFmpeg subprocess."""
    with _STUDIO_JOBS_LOCK:
        rec = _STUDIO_JOBS.get(job_id)
        cancel_ctx = _STUDIO_JOB_CANCELS.get(job_id)
        if not rec:
            return False
        if rec.get("status") == "running":
            rec["status"] = "cancelled"
            rec["stage"] = "Cancelled"
            rec["error"] = "Cancelled"
            rec["updated_at"] = time.time()
    if cancel_ctx:
        _kill_cancel_ctx(cancel_ctx)
    return True


def _infer_quality_label(
    out_w: int,
    out_h: int,
    src_w: int = 0,
    src_h: int = 0,
    src_quality: Any = None,
) -> Optional[str]:
    """Infer standard broadcast quality badge (e.g. 1920x960 ultrawide -> '1080p', never '960p')."""
    if out_w <= 0 or out_h <= 0:
        return None
    if src_w > 0 and src_h > 0 and out_w == src_w and out_h == src_h and src_quality:
        q = str(src_quality).strip()
        if q.isdigit():
            return f"{q}p"
        if q:
            return q
    long_side = max(out_w, out_h)
    short_side = min(out_w, out_h)
    if long_side >= 3840 or short_side >= 2160:
        return "2160p"
    if long_side >= 2560 or short_side >= 1440:
        return "1440p"
    if long_side >= 1920 or short_side >= 1080:
        return "1080p"
    if long_side >= 1280 or short_side >= 720:
        return "720p"
    if long_side >= 854 or short_side >= 480:
        return "480p"
    return f"{short_side}p"


def get_studio_render_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _STUDIO_JOBS_LOCK:
        rec = _STUDIO_JOBS.get(job_id)
        return dict(rec) if rec else None


_PRERENDER_LOCK = threading.Lock()
_PRERENDERS: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _kill_cancel_ctx(cancel_ctx: Optional[Dict[str, Any]]) -> None:
    if not isinstance(cancel_ctx, dict):
        return
    ev = cancel_ctx.get("event")
    if isinstance(ev, threading.Event):
        ev.set()
    ctx_lock = _get_ctx_lock(cancel_ctx)
    with ctx_lock:
        to_kill = list(cancel_ctx.get("procs") or ())
        single = cancel_ctx.get("proc")
        if single is not None and single not in to_kill:
            to_kill.append(single)
        children = list(cancel_ctx.get("children") or ())
    for child in children:
        _kill_cancel_ctx(child)
    for proc in to_kill:
        try:
            proc.kill()
        except Exception:
            pass


def cancel_studio_prerender(project_id: Optional[str] = None, clip_id: Optional[str] = None) -> int:
    """Cancel active background pre-render(s) cleanly and terminate their low-priority FFmpeg process."""
    to_stop: List[Dict[str, Any]] = []
    with _PRERENDER_LOCK:
        for (pid, cid), entry in list(_PRERENDERS.items()):
            if project_id is not None and pid != project_id:
                continue
            if clip_id is not None and cid != clip_id:
                continue
            if entry.get("status") == "running":
                entry["status"] = "cancelled"
                to_stop.append(entry)
    for entry in to_stop:
        _kill_cancel_ctx(entry.get("cancel_ctx"))
    return len(to_stop)


def _attach_or_cancel_prerender(
    project_id: str,
    clip_id: str,
    cache_key: str,
    out_path: str,
    *,
    progress_cb: Optional[Callable[[int], None]] = None,
    stage_cb: Optional[Callable[[str], None]] = None,
    cancel_ctx: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, bool]:
    """If an identical background pre-render is already running, attach live progress/cancel to it; else cancel stale ones.

    Returns ``(ok, cancelled)``.
    """
    matched: Optional[Dict[str, Any]] = None
    stale_to_stop: List[Dict[str, Any]] = []
    listener = (progress_cb, stage_cb)
    with _PRERENDER_LOCK:
        for key, entry in list(_PRERENDERS.items()):
            if entry.get("status") != "running":
                continue
            if key == (project_id, clip_id) and entry.get("cache_key") == cache_key:
                matched = entry
                entry["listeners"].append(listener)
            else:
                # Free GPU/CPU for the foreground Export/Download job
                entry["status"] = "cancelled"
                stale_to_stop.append(entry)
    for st in stale_to_stop:
        _kill_cancel_ctx(st.get("cancel_ctx"))
    for st in stale_to_stop:
        done_old = st.get("done_event")
        if isinstance(done_old, threading.Event):
            done_old.wait(timeout=5.0)

    if matched is None:
        return False, False

    if stage_cb:
        stage_cb(matched.get("stage") or "Rendering video...")
    if progress_cb and matched.get("progress", 0) > 0:
        progress_cb(min(99, int(matched["progress"])))

    fg_cancel_ev: Optional[threading.Event] = cancel_ctx.get("event") if isinstance(cancel_ctx, dict) else None
    done_ev: threading.Event = matched["done_event"]
    try:
        while not done_ev.wait(timeout=0.15):
            if fg_cancel_ev and fg_cancel_ev.is_set():
                with _PRERENDER_LOCK:
                    matched["status"] = "cancelled"
                _kill_cancel_ctx(matched.get("cancel_ctx"))
                return False, True
        if fg_cancel_ev and fg_cancel_ev.is_set():
            return False, True
        if matched.get("status") == "done" and os.path.isfile(out_path):
            if progress_cb:
                progress_cb(99)
            return True, False
        return False, False
    finally:
        with _PRERENDER_LOCK:
            try:
                matched["listeners"].remove(listener)
            except ValueError:
                pass


def start_studio_prerender(project_id: str, clip_id: str, edit_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Quietly pre-render a filtered Full Video clip in the background for fast export handoff."""
    if not ffmpeg_setup.ensure_ffmpeg():
        return {"ok": False, "status": "no_ffmpeg"}

    proj, folder, _, src_path, err = _resolve_project_clip(project_id, clip_id)
    if err or not proj or not folder or not src_path:
        return {"ok": False, "status": "not_found"}
    if get_studio_mode(proj) != "full_video":
        return {"ok": True, "status": "skipped_mode"}

    # Never compete with an active foreground Export or Download job
    with _STUDIO_JOBS_LOCK:
        if any(rec.get("status") == "running" for rec in _STUDIO_JOBS.values()):
            return {"ok": True, "status": "skipped_busy"}

    dur, width, height = _probe_video_info(src_path)
    fb_start = max(0.0, float(edit_payload.get("start", 0.0)))
    fb_end = float(edit_payload.get("end", dur or 30.0))
    segments = _sanitize_segments(edit_payload.get("segments"), dur or max(1.0, fb_end), fb_start, fb_end)
    pieces = _expand_segments_to_pieces(segments)
    out_dur = max(0.2, sum((e - s) / spd for s, e, spd, _, _, _ in pieces))

    muted = bool(edit_payload.get("muted", False))
    crop_ratio = _sanitize_crop_ratio(edit_payload.get("cropRatio"))
    fade = _sanitize_fade(edit_payload.get("fade"))
    color_cfg = _sanitize_color(edit_payload.get("color"))
    audio_enhance = _sanitize_audio_enhance(edit_payload.get("audioEnhance"))

    assets_dir = os.path.join(folder, STUDIO_ASSETS_DIR)
    audio_clips = _sanitize_audio_clips(
        edit_payload.get("audioClips"),
        project_id,
        assets_dir,
        out_dur,
        legacy_music=edit_payload.get("music") if isinstance(edit_payload.get("music"), dict) else None,
    )

    crop_filter = _build_crop_filter(crop_ratio, width, height)
    color_filters = _build_color_filters(color_cfg)
    has_speed_fx = any(abs(spd - 1.0) >= 0.01 for _, _, spd, _, _, _ in pieces)
    has_pixel_fx = bool(crop_filter or color_filters or fade > 0.0 or has_speed_fx)

    # Lossless tiers (Tier 0/1/1.5/2/2.5) already finish in 0..4s; only pre-render pixel-filtered clips
    if not has_pixel_fx:
        cancel_studio_prerender(project_id, clip_id)
        return {"ok": True, "status": "ready"}

    exports_dir = os.path.join(folder, STUDIO_EXPORTS_DIR)
    os.makedirs(exports_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src_path))[0]
    out_path = os.path.join(exports_dir, f"{stem}_studio.mp4")

    asset_paths = [
        p for p in (get_studio_music_path(project_id, str(ac.get("assetName") or "")) for ac in audio_clips) if p
    ]
    cache_spec = {
        "pieces": pieces,
        "muted": muted,
        "cropRatio": crop_ratio,
        "fade": fade,
        "color": color_cfg,
        "audioEnhance": audio_enhance,
        "audioClips": [
            {
                "assetName": ac.get("assetName"),
                "timelineStart": ac.get("timelineStart"),
                "trimStart": ac.get("trimStart"),
                "trimEnd": ac.get("trimEnd"),
                "volume": ac.get("volume"),
                "fadeIn": ac.get("fadeIn"),
                "fadeOut": ac.get("fadeOut"),
                "keyframes": ac.get("keyframes"),
            }
            for ac in audio_clips
        ],
    }
    cache_key = _compute_export_cache_key("full_video", src_path, cache_spec, asset_paths)
    if _try_reuse_cached_export(out_path, cache_key):
        return {"ok": True, "status": "cached"}

    stale_to_stop: List[Dict[str, Any]] = []
    entry: Dict[str, Any] = {
        "cache_key": cache_key,
        "status": "running",
        "progress": 0,
        "stage": "Rendering video...",
        "cancel_ctx": {"event": threading.Event(), "proc": None, "procs": set(), "lock": threading.Lock()},
        "done_event": threading.Event(),
        "listeners": [],
    }
    with _PRERENDER_LOCK:
        # Re-check active foreground jobs under lock after ffprobe latency (closes TOCTOU window)
        with _STUDIO_JOBS_LOCK:
            if any(rec.get("status") == "running" for rec in _STUDIO_JOBS.values()):
                return {"ok": True, "status": "skipped_busy"}
        existing = _PRERENDERS.get((project_id, clip_id))
        if existing and existing.get("status") == "running" and existing.get("cache_key") == cache_key:
            return {"ok": True, "status": "running", "progress": int(existing.get("progress") or 0)}
        # Allow at most 1 background pre-render across the app to keep every PC responsive
        for k, old in list(_PRERENDERS.items()):
            if old.get("status") == "running":
                old["status"] = "cancelled"
                stale_to_stop.append(old)
        _PRERENDERS[(project_id, clip_id)] = entry
    for old in stale_to_stop:
        _kill_cancel_ctx(old.get("cancel_ctx"))
    for old in stale_to_stop:
        done_old = old.get("done_event")
        if isinstance(done_old, threading.Event):
            done_old.wait(timeout=5.0)

    def _bg_prog(pct: int) -> None:
        with _PRERENDER_LOCK:
            if entry["status"] != "running":
                return
            entry["progress"] = max(int(entry["progress"] or 0), min(99, int(pct)))
            listeners = list(entry["listeners"])
        for p_cb, _ in listeners:
            if p_cb:
                try:
                    p_cb(entry["progress"])
                except Exception:
                    pass

    def _bg_stage(lbl: str) -> None:
        with _PRERENDER_LOCK:
            if entry["status"] != "running":
                return
            entry["stage"] = str(lbl or "")
            listeners = list(entry["listeners"])
        for _, s_cb in listeners:
            if s_cb:
                try:
                    s_cb(entry["stage"])
                except Exception:
                    pass

    def _bg_worker() -> None:
        try:
            rendered_path, _, render_err = _export_full_video_clip(
                project_id,
                folder,
                src_path,
                edit_payload,
                progress_cb=_bg_prog,
                stage_cb=_bg_stage,
                cancel_ctx=entry["cancel_ctx"],
                clip_id=clip_id,
                low_priority=True,
                allow_parallel=False,  # Single low-priority worker keeps timeline playback smooth
                attach_prerender=False,
            )
            with _PRERENDER_LOCK:
                if entry["cancel_ctx"]["event"].is_set() or render_err == "Cancelled":
                    entry["status"] = "cancelled"
                elif render_err or not rendered_path or not os.path.isfile(rendered_path):
                    entry["status"] = "error"
                else:
                    entry["status"] = "done"
                    entry["progress"] = 100
        except Exception:
            with _PRERENDER_LOCK:
                entry["status"] = "cancelled" if entry["cancel_ctx"]["event"].is_set() else "error"
        finally:
            entry["done_event"].set()

    threading.Thread(target=_bg_worker, daemon=True).start()
    return {"ok": True, "status": "started"}


_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)")


def detect_studio_silence(
    project_id: str,
    clip_id: str,
    edit_payload: Dict[str, Any],
    *,
    noise_db: float = -32.0,
    min_silence: float = 0.65,
    pad_sec: float = 0.15,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Detect silent pauses in active segments via fast -vn FFmpeg silencedetect and return clean cut segments."""
    if not ffmpeg_setup.ensure_ffmpeg():
        return None, "FFmpeg is not available on this system"

    _, _, _, src_path, err = _resolve_project_clip(project_id, clip_id)
    if err or not src_path:
        return None, err or "Clip not found"

    if not _probe_has_audio(src_path):
        return None, "Video has no audio track to analyze"

    dur, _, _ = _probe_video_info(src_path)
    fb_start = max(0.0, float(edit_payload.get("start", 0.0)))
    fb_end = float(edit_payload.get("end", dur or 30.0))
    segments = _sanitize_segments(edit_payload.get("segments"), dur or max(1.0, fb_end), fb_start, fb_end)
    if not segments:
        return None, "No active video blocks"

    min_s = min(float(s["sourceStart"]) for s in segments)
    max_e = max(float(s["sourceEnd"]) for s in segments)
    span = max(0.2, max_e - min_s)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-vn",
        "-ss",
        f"{min_s:.3f}",
        "-t",
        f"{span:.3f}",
        "-i",
        src_path,
        "-af",
        f"silencedetect=noise={noise_db:.1f}dB:d={min_silence:.2f}",
        "-f",
        "null",
        "-",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
    except subprocess.TimeoutExpired:
        return None, "Silence detection timed out"
    if res.returncode != 0:
        err_tail = (res.stderr or "Silence detection failed").strip()[-240:]
        return None, f"Silence detection failed: {err_tail}"

    # Parse silence intervals (relative to min_s) and convert back to absolute source timestamps
    raw_silences: List[Tuple[float, float]] = []
    cur_start: Optional[float] = None
    for line in (res.stderr or "").splitlines():
        ms = _SILENCE_START_RE.search(line)
        if ms:
            cur_start = min_s + max(0.0, float(ms.group(1)))
            continue
        me = _SILENCE_END_RE.search(line)
        if me:
            end_t = min_s + max(0.0, float(me.group(1)))
            st_t = cur_start if cur_start is not None else min_s
            if end_t > st_t:
                raw_silences.append((st_t, end_t))
            cur_start = None
    if cur_start is not None and max_e > cur_start:
        raw_silences.append((cur_start, max_e))

    # Shrink each silence inward by pad_sec so speech attacks/tails stay natural
    cut_intervals: List[Tuple[float, float]] = []
    for s0, s1 in raw_silences:
        c0 = s0 + pad_sec
        c1 = s1 - pad_sec
        if c1 - c0 >= 0.25:
            cut_intervals.append((c0, c1))

    before_dur = sum(float(s["sourceEnd"]) - float(s["sourceStart"]) for s in segments)
    if not cut_intervals:
        return {
            "ok": True,
            "segments": segments,
            "removedCount": 0,
            "savedSec": 0.0,
            "beforeDur": round(before_dur, 2),
            "afterDur": round(before_dur, 2),
        }, None

    # Subtract silence cuts from every segment while preserving per-block props
    kept: List[Dict[str, Any]] = []
    removed_count = 0
    for seg in segments:
        pieces_cur: List[Tuple[float, float]] = [(float(seg["sourceStart"]), float(seg["sourceEnd"]))]
        for c0, c1 in cut_intervals:
            next_pieces: List[Tuple[float, float]] = []
            for a, b in pieces_cur:
                if c1 <= a or c0 >= b:
                    next_pieces.append((a, b))
                else:
                    removed_count += 1
                    if c0 - a >= 0.25:
                        next_pieces.append((a, c0))
                    if b - c1 >= 0.25:
                        next_pieces.append((c1, b))
            pieces_cur = next_pieces
        for a, b in pieces_cur:
            if b - a < 0.25:
                continue
            # Merge tiny gaps (<0.30s) inside same parent segment so cuts stay clean
            if (
                kept
                and kept[-1].get("_parent") == seg["id"]
                and (a - float(kept[-1]["sourceEnd"])) < 0.30
            ):
                kept[-1]["sourceEnd"] = round(b, 3)
            else:
                clone = dict(seg)
                clone["_parent"] = seg["id"]
                clone["sourceStart"] = round(a, 3)
                clone["sourceEnd"] = round(b, 3)
                kept.append(clone)

    if not kept:
        # Never wipe the whole timeline if entire clip is quiet
        return {
            "ok": True,
            "segments": segments,
            "removedCount": 0,
            "savedSec": 0.0,
            "beforeDur": round(before_dur, 2),
            "afterDur": round(before_dur, 2),
        }, None

    # Enforce _sanitize_segments 40-block cap safely without inverting reordered or cross-parent blocks
    while len(kept) > 40:
        mergeable = [
            i
            for i in range(len(kept) - 1)
            if kept[i].get("_parent") == kept[i + 1].get("_parent")
            and float(kept[i + 1]["sourceStart"]) >= float(kept[i]["sourceEnd"]) - 1e-3
        ]
        if mergeable:
            best_i = min(
                mergeable,
                key=lambda i: max(0.0, float(kept[i + 1]["sourceStart"]) - float(kept[i]["sourceEnd"])),
            )
            kept[best_i]["sourceEnd"] = kept[best_i + 1]["sourceEnd"]
            kept.pop(best_i + 1)
        else:
            shortest_i = min(
                range(len(kept)),
                key=lambda i: max(0.0, float(kept[i]["sourceEnd"]) - float(kept[i]["sourceStart"])),
            )
            kept.pop(shortest_i)

    final_segs: List[Dict[str, Any]] = []
    for idx, item in enumerate(kept):
        item.pop("_parent", None)
        item["id"] = f"seg_sc_{idx + 1}_{uuid.uuid4().hex[:4]}"
        final_segs.append(item)

    after_dur = sum(float(s["sourceEnd"]) - float(s["sourceStart"]) for s in final_segs)
    saved_sec = max(0.0, before_dur - after_dur)
    return {
        "ok": True,
        "segments": final_segs,
        "removedCount": removed_count if saved_sec >= 0.2 else 0,
        "savedSec": round(saved_sec, 2),
        "beforeDur": round(before_dur, 2),
        "afterDur": round(after_dur, 2),
    }, None


def get_studio_cache_path(project_id: str, filename: str) -> Optional[str]:
    """Safely resolve a cached sprite/artifact file inside a project's ``studio_cache/`` folder."""
    found = find_studio_project(project_id)
    if not found:
        return None
    _, folder = found
    safe_name = os.path.basename(str(filename or ""))
    if not safe_name or safe_name in (".", ".."):
        return None
    cache_dir = os.path.realpath(os.path.join(folder, STUDIO_CACHE_DIR))
    candidate = os.path.realpath(os.path.join(cache_dir, safe_name))
    try:
        if os.path.commonpath([cache_dir, candidate]) != cache_dir:
            return None
    except ValueError:
        return None
    return candidate if os.path.isfile(candidate) else None


def get_or_build_studio_filmstrip(
    project_id: str, clip_id: str, *, cols: int = 6, rows: int = 4, tile_w: int = 160, tile_h: int = 90
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Generate (once) and cache a lightweight JPEG filmstrip sprite sheet for instant timeline thumbnails."""
    if not ffmpeg_setup.ensure_ffmpeg():
        return None, "FFmpeg is not available"

    _, folder, _, src_path, err = _resolve_project_clip(project_id, clip_id)
    if err or not folder or not src_path:
        return None, err or "Clip not found"

    dur, _, _ = _probe_video_info(src_path)
    if dur <= 0.1:
        return None, "Invalid video duration"

    cache_dir = os.path.join(folder, STUDIO_CACHE_DIR)
    os.makedirs(cache_dir, exist_ok=True)
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", os.path.splitext(os.path.basename(src_path))[0])[:48] or "clip"
    sig_hash = hashlib.sha1(json.dumps(_file_stat_sig(src_path)).encode("utf-8")).hexdigest()[:10]
    sprite_name = f"{safe_stem}_{sig_hash}_filmstrip.jpg"
    meta_name = f"{safe_stem}_{sig_hash}_filmstrip.json"
    sprite_path = os.path.join(cache_dir, sprite_name)
    meta_path = os.path.join(cache_dir, meta_name)

    sprite_lock = _get_export_file_lock(sprite_path)
    with sprite_lock:
        if os.path.isfile(sprite_path) and os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if isinstance(cached, dict) and cached.get("sprite") == sprite_name:
                    cached["ok"] = True
                    cached["url"] = f"/api/studio/{quote(project_id, safe='')}/cache/{quote(sprite_name, safe='')}"
                    return cached, None
            except Exception:
                pass

        count = max(4, min(30, cols * rows))
        fps_val = max(0.002, count / max(0.5, dur))
        vf = (
            f"fps={fps_val:.6f},"
            f"scale={tile_w}:{tile_h}:force_original_aspect_ratio=increase,"
            f"crop={tile_w}:{tile_h},"
            f"tile={cols}x{rows}"
        )
        tmp_sprite = f"{sprite_path}.{uuid.uuid4().hex[:8]}.tmp.jpg"

        def _cleanup_sprite_tmp() -> None:
            if os.path.exists(tmp_sprite):
                try:
                    os.remove(tmp_sprite)
                except OSError:
                    pass

        cmd = ["ffmpeg", "-y"]
        if dur >= 24.0:
            # Keyframe-only decode makes 30-60 min filmstrip generation ~10x faster
            cmd += ["-skip_frame", "nokey"]
        cmd += ["-i", src_path, "-vf", vf, "-frames:v", "1", "-q:v", "5", tmp_sprite]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=45, check=False)
            if (res.returncode != 0 or not os.path.isfile(tmp_sprite) or os.path.getsize(tmp_sprite) < 256) and dur >= 24.0:
                _cleanup_sprite_tmp()
                # Fallback without -skip_frame nokey for sparse-keyframe files
                cmd_fb = ["ffmpeg", "-y", "-i", src_path, "-vf", vf, "-frames:v", "1", "-q:v", "5", tmp_sprite]
                res = subprocess.run(cmd_fb, capture_output=True, text=True, timeout=45, check=False)
        except subprocess.TimeoutExpired:
            _cleanup_sprite_tmp()
            return None, "Filmstrip generation timed out"

        if res.returncode != 0 or not os.path.isfile(tmp_sprite) or os.path.getsize(tmp_sprite) < 256:
            _cleanup_sprite_tmp()
            return None, "Could not generate filmstrip sprite"

        try:
            os.replace(tmp_sprite, sprite_path)
        except OSError:
            _cleanup_sprite_tmp()
            return None, "Could not save filmstrip sprite"

        step = dur / float(count)
        times = [round(min(dur - 0.05, (i + 0.5) * step), 2) for i in range(count)]
        manifest: Dict[str, Any] = {
            "ok": True,
            "sprite": sprite_name,
            "url": f"/api/studio/{quote(project_id, safe='')}/cache/{quote(sprite_name, safe='')}",
            "cols": cols,
            "rows": rows,
            "tileW": tile_w,
            "tileH": tile_h,
            "count": count,
            "dur": round(dur, 3),
            "times": times,
        }
        try:
            tmp_m = f"{meta_path}.{uuid.uuid4().hex[:8]}.tmp"
            with open(tmp_m, "w", encoding="utf-8") as f:
                json.dump(manifest, f)
            os.replace(tmp_m, meta_path)
        except Exception:
            pass
        return manifest, None
