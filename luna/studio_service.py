# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

"""Isolated backend service for Luna AI Clipper Studio.

All edits are stored non-destructively in ``studio_state.json`` inside the
project folder, uploaded music lives in ``studio_assets/``, and rendered
exports are written to ``studio_exports/`` so original AI Clipper MP4 files
and ``meta.json`` are never overwritten.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Tuple

from . import ffmpeg_setup, storage_manager, vault_service

STUDIO_STATE_FILE = "studio_state.json"
STUDIO_ASSETS_DIR = "studio_assets"
STUDIO_EXPORTS_DIR = "studio_exports"
ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".webm"}
MAX_AUDIO_BYTES = 60 * 1024 * 1024  # 60 MB


def _is_ai_short_clips_project(proj: Dict[str, Any]) -> bool:
    if not isinstance(proj, dict) or proj.get("virtual"):
        return False
    act = str(proj.get("action") or "").lower()
    cat = str(proj.get("category") or "").lower()
    if act in ("type_yt_clip", "manual_clip") or "trim" in cat:
        return False
    if "ai_clip" in act or "01-ai-clips" in cat:
        return True
    files = proj.get("files") or []
    return any(
        "ai_clip" in str(f.get("action") or "").lower()
        or "01-ai-clips" in str(f.get("category") or "").lower()
        for f in files
        if isinstance(f, dict)
    )


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
        if not _is_ai_short_clips_project(proj):
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


def _media_vault_url(abs_path: str) -> str:
    root = os.path.abspath(storage_manager.get_storage_root())
    try:
        rel = os.path.relpath(os.path.abspath(abs_path), root).replace("\\", "/")
        return f"/media-vault/{rel}"
    except ValueError:
        return ""


def _probe_video_info(video_path: str) -> Tuple[float, int, int]:
    """Return (duration_sec, width, height) using ffprobe, with safe fallbacks."""
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
            "stream=width,height:format=duration",
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
                width = int(streams[0].get("width") or width)
                height = int(streams[0].get("height") or height)
    except Exception:
        pass
    return dur, width, height


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


def load_studio_project(project_id: str) -> Optional[Dict[str, Any]]:
    found = find_studio_project(project_id)
    if not found:
        return None
    proj, folder = found
    saved = _read_studio_state(folder)
    saved_clips = {
        c.get("id"): c for c in (saved.get("clips") or []) if isinstance(c, dict) and c.get("id")
    }

    source_srt_path = _find_project_source_srt(proj, folder)
    source_cues = _parse_srt_file(source_srt_path) if source_srt_path else []

    assets_dir = os.path.join(folder, STUDIO_ASSETS_DIR)
    clips: List[Dict[str, Any]] = []
    video_files = [
        f
        for f in (proj.get("files") or [])
        if isinstance(f, dict) and str(f.get("type") or "video").lower() != "audio"
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

        stem = os.path.splitext(clip_path)[0]
        default_cues = _parse_srt_file(f"{stem}.srt")
        if not default_cues and source_cues and src_en > src_st:
            default_cues = _slice_cues_for_clip(source_cues, src_st, src_en)
        saved_clip_cues = sc.get("cues") if isinstance(sc.get("cues"), list) else None
        cues = saved_clip_cues if (saved_clip_cues and len(saved_clip_cues) > 0) else default_cues

        start = max(0.0, float(sc.get("start", 0.0)))
        end = min(dur, max(start + 1.0, float(sc.get("end", dur))))

        music_meta = None
        raw_music = sc.get("music")
        if isinstance(raw_music, dict) and raw_music.get("assetName"):
            asset_base = os.path.basename(str(raw_music["assetName"]))
            asset_full = os.path.join(assets_dir, asset_base)
            if os.path.isfile(asset_full):
                music_meta = {
                    "name": str(raw_music.get("name") or asset_base),
                    "assetName": asset_base,
                    "url": f"/api/studio/{project_id}/music/{asset_base}",
                    "totalDur": float(raw_music.get("totalDur") or dur),
                    "sliceStart": max(0.0, float(raw_music.get("sliceStart") or 0.0)),
                    "volume": max(0, min(100, int(raw_music.get("volume", 35)))),
                    "peaks": raw_music.get("peaks") if isinstance(raw_music.get("peaks"), list) else [],
                }

        clip_title = str(sc.get("title") if sc.get("title") is not None else (f.get("title") or f"Clip {idx + 1}"))
        clip_caption = str(sc.get("caption") if sc.get("caption") is not None else (f.get("caption") or ""))
        clip_tags = (
            str(sc.get("tags"))
            if sc.get("tags") is not None
            else _generate_adaptive_hashtags(clip_title, clip_caption)
        )

        clips.append(
            {
                "id": clip_id,
                "name": f"Clip {idx + 1}",
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
            }
        )

    return {
        "project_id": project_id,
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

    clean_clips = []
    for c in payload.get("clips") or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        clean_music = None
        m = c.get("music")
        if isinstance(m, dict) and m.get("assetName"):
            clean_music = {
                "name": str(m.get("name") or ""),
                "assetName": os.path.basename(str(m["assetName"])),
                "totalDur": float(m.get("totalDur") or 0.0),
                "sliceStart": max(0.0, float(m.get("sliceStart") or 0.0)),
                "volume": max(0, min(100, int(m.get("volume", 35)))),
                "peaks": [round(float(x), 4) for x in (m.get("peaks") or [])[:256]],
            }
        clean_cues = []
        for q in c.get("cues") or []:
            if isinstance(q, dict) and isinstance(q.get("text"), str):
                clean_cues.append(
                    {
                        "start": round(max(0.0, float(q.get("start") or 0.0)), 3),
                        "end": round(max(0.0, float(q.get("end") or 0.0)), 3),
                        "text": q["text"],
                    }
                )
        clean_clips.append(
            {
                "id": str(c["id"]),
                "dur": round(max(0.0, float(c.get("dur") or 0.0)), 3),
                "start": round(max(0.0, float(c.get("start") or 0.0)), 3),
                "end": round(max(0.0, float(c.get("end") or 0.0)), 3),
                "title": str(c.get("title") or ""),
                "tags": str(c.get("tags") or ""),
                "caption": str(c.get("caption") or ""),
                "cues": clean_cues,
                "music": clean_music,
            }
        )

    state_doc = {
        "subStyle": str(payload.get("subStyle") or "none"),
        "subSize": str(payload.get("subSize") or "medium"),
        "customScale": max(0, min(200, int(payload.get("customScale", 100)))),
        "subPos": str(payload.get("subPos") or "bottom"),
        "posX": max(15.0, min(85.0, float(payload.get("posX", 50.0)))),
        "posY": max(10.0, min(92.0, float(payload.get("posY", 78.0)))),
        "clips": clean_clips,
    }
    vault_service._atomic_write_json(os.path.join(folder, STUDIO_STATE_FILE), state_doc)
    return state_doc


def save_studio_music(
    project_id: str, clip_id: str, original_filename: str, data: bytes
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    found = find_studio_project(project_id)
    if not found:
        return None, "Project not found"
    _, folder = found
    if not data:
        return None, "Empty audio file"
    if len(data) > MAX_AUDIO_BYTES:
        return None, "Audio file exceeds 60 MB limit"

    display_name = os.path.basename(original_filename or "music.mp3").strip() or "music.mp3"
    ext = os.path.splitext(display_name)[1].lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        return None, f"Unsupported audio format ({ext or 'unknown'})"

    safe_clip = re.sub(r"[^a-zA-Z0-9_-]", "", clip_id or "clip")[:24] or "clip"
    asset_name = f"{safe_clip}_{uuid.uuid4().hex[:8]}{ext}"
    assets_dir = os.path.join(folder, STUDIO_ASSETS_DIR)
    os.makedirs(assets_dir, exist_ok=True)
    target = os.path.join(assets_dir, asset_name)
    if not vault_service._is_inside_storage(target, storage_manager.get_storage_root()):
        return None, "Invalid storage path"

    with open(target, "wb") as f:
        f.write(data)

    return {
        "name": display_name,
        "assetName": asset_name,
        "url": f"/api/studio/{project_id}/music/{asset_name}",
    }, None


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
    # Skip leading <0.25s SRT boundary stub just like the browser preview
    if len(valid_cues) > 1 and (float(valid_cues[0].get("end", 0)) - float(valid_cues[0].get("start", 0))) < 0.25:
        valid_cues = valid_cues[1:]
        valid_cues[0] = {**valid_cues[0], "start": 0.0}

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
            mid = rel_start + (rel_end - rel_start) * 0.5
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


def export_studio_clip(
    project_id: str, clip_id: str, edit_payload: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Render an edited MP4 into ``studio_exports/`` without touching the original clip."""
    if not ffmpeg_setup.ensure_ffmpeg():
        return None, None, "FFmpeg is not available on this system"

    found = find_studio_project(project_id)
    if not found:
        return None, None, "Project not found"
    proj, folder = found

    target_file = None
    for idx, f in enumerate(proj.get("files") or []):
        if isinstance(f, dict) and str(f.get("id") or f"clip_{idx + 1}") == clip_id:
            target_file = f
            break
    if not target_file:
        return None, None, "Clip not found"

    src_path = _resolve_clip_path(target_file, folder)
    if not src_path:
        return None, None, "Source clip file is missing on disk"

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
        music_slice_start = max(0.0, float(music_cfg.get("sliceStart") or 0.0))
        music_vol = max(0.0, min(1.0, float(music_cfg.get("volume", 35)) / 100.0))

    exports_dir = os.path.join(folder, STUDIO_EXPORTS_DIR)
    os.makedirs(exports_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src_path))[0]
    download_name = f"{stem}_studio.mp4"
    out_path = os.path.join(exports_dir, download_name)

    ass_tmp: Optional[str] = None
    try:
        cmd: List[str] = ["ffmpeg", "-y", "-ss", f"{trim_start:.3f}", "-to", f"{trim_end:.3f}", "-i", src_path]
        if music_path:
            cmd += ["-stream_loop", "-1", "-ss", f"{music_slice_start:.3f}", "-t", f"{clip_span:.3f}", "-i", music_path]

        vf_parts: List[str] = []
        if sub_style == "selene" and cues:
            ass_content = _build_selene_ass(cues, trim_start, trim_end, width, height, size_scale, pos_x, pos_y)
            fd, ass_tmp = tempfile.mkstemp(prefix="luna_studio_", suffix=".ass")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(ass_content)
            vf_parts.append(f"ass='{_escape_ffmpeg_filter_path(ass_tmp)}'")

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
            cmd += ["-filter_complex", ";".join(fc_parts), "-map", v_map, "-map", "[aout]"]
        else:
            if vf_parts:
                cmd += ["-vf", ",".join(vf_parts)]
            if muted:
                cmd += ["-map", "0:v:0", "-an"]
            else:
                cmd += ["-map", "0:v:0", "-map", "0:a?"]

        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            out_path,
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        if res.returncode != 0 or not os.path.isfile(out_path):
            err_tail = (res.stderr or res.stdout or "FFmpeg render failed").strip()[-350:]
            return None, None, f"Render failed: {err_tail}"
        return out_path, download_name, None
    finally:
        if ass_tmp and os.path.exists(ass_tmp):
            try:
                os.remove(ass_tmp)
            except OSError:
                pass
