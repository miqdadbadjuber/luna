import asyncio
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import ipaddress
import time
import urllib.parse
import uuid
import zipfile
from typing import Any, Callable, Dict, List, Optional

import requests
import yt_dlp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AI_CLIPPER_DIR = os.path.join(BASE_DIR, "AI-Clipper")
sys.path.append(AI_CLIPPER_DIR)

# Load environment variables
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Ensure ffmpeg in PATH
os.environ["PATH"] += os.pathsep + r"C:\ffmpeg\bin"

from shorts_generator import generate_shorts
from shorts_generator.highlights import clean_caption
from storage_manager import (
    CATEGORY_MAP,
    get_storage_root,
    get_category_folder,
    get_workspace_folder,
    format_media_filename,
    format_clip_folder,
    is_writable,
)
from vault_service import (
    save_media_metadata,
    save_project_metadata,
    list_vault_items,
    list_vault_projects,
    rename_vault_project,
    delete_vault_project,
    get_next_workspace_index,
    delete_vault_item,
    get_storage_stats,
)

OUTPUT_DIR = os.path.join(BASE_DIR, "output")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)

app = FastAPI(title="Luna: Multi-Platform Media & AI Shorts Web Studio")

storage_root = get_storage_root()
os.makedirs(storage_root, exist_ok=True)


class DynamicStorageStaticFiles(StaticFiles):
    def lookup_path(self, path: str):
        curr_root = get_storage_root()
        dirs = [curr_root]
        fallback = os.path.abspath(OUTPUT_DIR)
        if fallback != os.path.abspath(curr_root) and os.path.exists(fallback):
            dirs.append(fallback)
        self.all_directories = dirs
        return super().lookup_path(path)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/media-vault", DynamicStorageStaticFiles(directory=storage_root), name="media-vault")

jobs: Dict[str, Dict] = {}


def _prune_old_jobs(max_keep: int = 50):
    """Keep memory tidy by removing oldest completed, cancelled, or failed jobs when job count exceeds max_keep."""
    if len(jobs) <= max_keep:
        return
    terminal_keys = [
        k for k, v in jobs.items()
        if v.get("status") in ("completed", "failed", "cancelled")
    ]
    for k in terminal_keys:
        if len(jobs) <= max_keep:
            break
        jobs.pop(k, None)


def is_safe_external_url(url: str) -> bool:
    """Validate that the URL has an HTTP/HTTPS scheme and doesn't target private or local networks (SSRF prevention)."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        hostname_lower = hostname.lower()
        if hostname_lower in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False
        try:
            ip = ipaddress.ip_address(hostname_lower)
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                return False
        except ValueError:
            pass
        return True
    except Exception:
        return False


# Utilities
def sanitize_title(title: str) -> str:
    title = re.sub(r'#\S+', '', title)
    title = re.sub(r'[\\/*?:"<>|]', '', title)
    title = ' '.join(title.split()).strip()
    return title[:80].strip() or "media"


def parse_timestamp(ts: str) -> float:
    ts = str(ts).strip()
    parts = ts.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(ts)
    except:
        return 0.0


def get_ytdl_base_opts(extra_opts=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
    }
    cookie_file = os.path.join(BASE_DIR, "cookies.txt")
    if os.path.exists(cookie_file) and os.path.getsize(cookie_file) > 0:
        opts["cookiefile"] = cookie_file
    if extra_opts:
        opts.update(extra_opts)
    return opts


def detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "tiktok.com" in url_lower:
        return "tiktok"
    if "instagram.com" in url_lower or "instagr.am" in url_lower:
        return "instagram"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    return "unknown"


def _safe_join(base_dir: str, *parts: str) -> str:
    base_abs = os.path.abspath(base_dir)
    candidate = os.path.abspath(os.path.join(base_abs, *parts))
    try:
        if os.path.commonpath([base_abs, candidate]) != base_abs:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    return candidate


def _safe_output_job_dir(job_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id or ""):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    return _safe_join(OUTPUT_DIR, job_id)


def _safe_output_file(job_id: str, filename: str) -> str:
    if (
        not filename
        or filename != os.path.basename(filename)
        or any(sep in filename for sep in ("/", "\\"))
    ):
        raise HTTPException(status_code=400, detail="Invalid file name")
    return _safe_join(_safe_output_job_dir(job_id), filename)


def _path_is_inside(path: str, roots: List[str]) -> bool:
    target = os.path.realpath(os.path.abspath(os.path.normpath(path)))
    for root in roots:
        root_abs = os.path.realpath(os.path.abspath(root))
        try:
            if os.path.commonpath([root_abs, target]) == root_abs:
                return True
        except ValueError:
            continue
    return False


# Progress hook factory for yt-dlp & streaming downloads
def create_progress_hook(job_id: str):
    def hook(d: dict):
        if job_id not in jobs:
            return
        if jobs.get(job_id, {}).get("cancelled"):
            raise RuntimeError("CANCELLED_BY_USER")
        status = d.get("status")
        if status == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            pct = 0.0
            if total and total > 0:
                pct = round((downloaded / total) * 100, 1)
            else:
                p_str = str(d.get("_percent_str", "")).strip().replace("%", "")
                try:
                    pct = round(float(p_str), 1)
                except (ValueError, TypeError):
                    frags = d.get("fragment_index")
                    frag_total = d.get("fragment_count")
                    if frags and frag_total:
                        pct = round((frags / frag_total) * 100, 1)

            pct = min(max(pct, 0.0), 99.9)

            speed = d.get("speed")
            speed_str = ""
            if speed:
                if speed >= 1024 * 1024:
                    speed_str = f"{speed / (1024 * 1024):.1f} MB/s"
                elif speed >= 1024:
                    speed_str = f"{speed / 1024:.0f} KB/s"
                else:
                    speed_str = f"{speed:.0f} B/s"

            eta = d.get("eta")
            eta_str = ""
            if eta is not None:
                mins, secs = divmod(int(eta), 60)
                eta_str = f"{mins:02d}:{secs:02d}"

            frags_str = ""
            if d.get("fragment_index") and d.get("fragment_count"):
                frags_str = f"{d.get('fragment_index')}/{d.get('fragment_count')} frag"

            jobs[job_id]["progress"] = pct
            jobs[job_id]["download_speed"] = speed_str
            jobs[job_id]["download_eta"] = eta_str
            jobs[job_id]["download_frags"] = frags_str
            jobs[job_id]["downloaded_bytes"] = downloaded
            jobs[job_id]["total_bytes"] = total or 0
        elif status == "finished":
            jobs[job_id]["download_speed"] = ""
            jobs[job_id]["download_eta"] = ""
            jobs[job_id]["download_frags"] = ""
            if jobs.get(job_id, {}).get("action") in ("type_yt_ai_clip", "type_ig_ai_clip", "ai_clip"):
                jobs[job_id]["progress"] = 25.0
            else:
                jobs[job_id]["progress"] = 100.0
    return hook


# Download engines
def download_youtube_video(url: str, output_dir: str, quality: str = "1080", progress_hook: Optional[Callable] = None) -> str:
    h = {"1080": 1080, "720": 720, "480": 480, "360": 360}.get(quality, 1080)
    base_opts = {
        "format": f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best",
        "outtmpl": os.path.join(output_dir, "video.%(ext)s"),
        "merge_output_format": "mp4",
    }
    if progress_hook:
        base_opts["progress_hooks"] = [progress_hook]
    opts = get_ytdl_base_opts(base_opts)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "video")
        clean = sanitize_title(title)
        for ext in ["mp4", "mkv", "webm"]:
            candidate = os.path.join(output_dir, f"video.{ext}")
            if os.path.exists(candidate):
                dst = os.path.join(output_dir, f"{clean}.{ext}")
                if os.path.exists(dst): os.remove(dst)
                os.rename(candidate, dst)
                return dst
        return ydl.prepare_filename(info)


def download_instagram_reels(url: str, output_dir: str, progress_hook: Optional[Callable] = None) -> str:
    opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": os.path.join(output_dir, "reels.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "http_headers": {
            "User-Agent": "Instagram 219.0.0.12.117 Android (28/9; 411dpi; 1080x2226; Xiaomi; Mi A2; jasmine_sprout; qcom; en_US; 302733750)"
        }
    }
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "instagram_reels")
        clean = sanitize_title(title)
        for ext in ["mp4", "mkv", "webm", "mov"]:
            candidate = os.path.join(output_dir, f"reels.{ext}")
            if os.path.exists(candidate):
                dst = os.path.join(output_dir, f"{clean}.{ext}")
                if os.path.exists(dst): os.remove(dst)
                os.rename(candidate, dst)
                return dst
        return ydl.prepare_filename(info)


def download_tiktok_video(url: str, output_dir: str, progress_hook: Optional[Callable] = None) -> str:
    import urllib.request
    if "vt.tiktok.com" in url or "vm.tiktok.com" in url:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                url = resp.url
        except: pass

    # Try yt-dlp impersonation
    for target in ["Chrome-136", "Firefox-135", "Edge-101"]:
        try:
            opts = {
                "format": "bestvideo[ext=mp4]+bestaudio/bestvideo+bestaudio/best",
                "outtmpl": os.path.join(output_dir, "video.%(ext)s"),
                "merge_output_format": "mp4",
                "quiet": True,
                "impersonate": target,
            }
            if progress_hook:
                opts["progress_hooks"] = [progress_hook]
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "tiktok")
                clean = sanitize_title(title)
                for ext in ["mp4", "mkv", "webm"]:
                    candidate = os.path.join(output_dir, f"video.{ext}")
                    if os.path.exists(candidate):
                        dst = os.path.join(output_dir, f"{clean}.{ext}")
                        if os.path.exists(dst): os.remove(dst)
                        os.rename(candidate, dst)
                        return dst
                return ydl.prepare_filename(info)
        except:
            continue

    # Fallback to tikwm with live progress
    try:
        r = requests.get(f"https://www.tikwm.com/api/?url={url}&hd=1", timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        if data.get("code") == 0:
            video_url = data["data"].get("hdplay") or data["data"].get("play")
            title = data["data"].get("title", "tiktok")
            clean = sanitize_title(title)
            out_path = os.path.join(output_dir, f"{clean}.mp4")
            with requests.get(video_url, stream=True, timeout=120) as vr:
                total_len = int(vr.headers.get("content-length", 0))
                downloaded = 0
                t0 = time.time()
                with open(out_path, "wb") as f:
                    for chunk in vr.iter_content(chunk_size=512*1024):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_hook:
                                now = time.time()
                                dur = max(0.001, now - t0)
                                speed = downloaded / dur
                                eta = (total_len - downloaded) / speed if (total_len and speed > 0) else None
                                progress_hook({
                                    "status": "downloading",
                                    "downloaded_bytes": downloaded,
                                    "total_bytes": total_len,
                                    "speed": speed,
                                    "eta": eta,
                                })
            if progress_hook:
                progress_hook({"status": "finished"})
            return out_path
    except: pass

    raise RuntimeError("All TikTok download methods failed. Try another link.")


def download_mp3(url: str, output_dir: str, progress_hook: Optional[Callable] = None) -> str:
    base_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_dir, "audio.%(ext)s"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}],
    }
    if progress_hook:
        base_opts["progress_hooks"] = [progress_hook]
    opts = get_ytdl_base_opts(base_opts)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "audio")
    clean = sanitize_title(title)
    src = os.path.join(output_dir, "audio.mp3")
    dst = os.path.join(output_dir, f"{clean}.mp3")
    if os.path.exists(src):
        if os.path.exists(dst): os.remove(dst)
        os.rename(src, dst)
        return dst
    return src


def download_and_clip(
    url: str,
    output_dir: str,
    start_sec: float,
    end_sec: float,
    ratio: str = "16:9",
    progress_hook: Optional[Callable] = None,
    on_stage: Optional[Callable[[str], None]] = None,
) -> str:
    base_opts = {
        "format": "bestvideo[height<=1080]+bestaudio/best",
        "outtmpl": os.path.join(output_dir, "full.%(ext)s"),
        "merge_output_format": "mp4",
    }
    if progress_hook:
        base_opts["progress_hooks"] = [progress_hook]
    opts = get_ytdl_base_opts(base_opts)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "video")

    full_path = None
    for ext in ["mp4", "mkv", "webm"]:
        candidate = os.path.join(output_dir, f"full.{ext}")
        if os.path.exists(candidate):
            full_path = candidate
            break
    if not full_path:
        raise RuntimeError("Downloaded file was not found")

    if on_stage:
        on_stage("clipping")

    clean = sanitize_title(title)
    out_clip = os.path.join(output_dir, f"{clean}_clip.mp4")

def extract_clip_segment(
    source_path: str,
    out_clip: str,
    start_sec: float,
    end_sec: float,
    ratio: str = "16:9",
) -> str:
    if ratio in ("9:16", "916"):
        vf = "crop=ih*9/16:ih,scale=1080:1920"
    elif ratio in ("3:4", "34"):
        vf = "crop=ih*3/4:ih,scale=810:1080"
    elif ratio in ("1:1", "11"):
        vf = "crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080"
    elif ratio in ("original", "source"):
        vf = ""
    else:
        vf = "scale=1920:1080"

    dur = max(0.5, end_sec - start_sec)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start_sec:.3f}",
        "-t", f"{dur:.3f}",
        "-i", source_path,
    ]
    if vf:
        cmd.extend(["-vf", vf])
    cmd.extend([
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-threads", "0",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_clip,
    ])
    subprocess.run(cmd, check=True)
    return out_clip


def download_and_clip(
    url: str,
    output_dir: str,
    start_sec: float,
    end_sec: float,
    ratio: str = "16:9",
    progress_hook: Optional[Callable] = None,
    on_stage: Optional[Callable[[str], None]] = None,
) -> str:
    base_opts = {
        "format": "bestvideo[height<=1080]+bestaudio/best",
        "outtmpl": os.path.join(output_dir, "full.%(ext)s"),
        "merge_output_format": "mp4",
    }
    if progress_hook:
        base_opts["progress_hooks"] = [progress_hook]
    opts = get_ytdl_base_opts(base_opts)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "video")

    full_path = None
    for ext in ["mp4", "mkv", "webm"]:
        candidate = os.path.join(output_dir, f"full.{ext}")
        if os.path.exists(candidate):
            full_path = candidate
            break
    if not full_path:
        raise RuntimeError("Downloaded file was not found")

    if on_stage:
        on_stage("clipping")

    clean = sanitize_title(title)
    out_clip = os.path.join(output_dir, f"{clean}_clip.mp4")
    return extract_clip_segment(full_path, out_clip, start_sec, end_sec, ratio)


def format_video_target(input_path: str, ratio: str = "original", fps: str = "auto") -> str:
    """
    Format full video to target aspect ratio (original, 9:16, 3:4, 1:1) and FPS (auto, 60, 30).
    Returns path to the formatted video file (or original if unchanged).
    """
    if ratio == "original" and (not fps or fps == "auto"):
        return input_path

    base_dir = os.path.dirname(input_path)
    base_name, _ = os.path.splitext(os.path.basename(input_path))
    ratio_tag = ratio.replace(":", "x") if ratio != "original" else ""
    fps_tag = f"{fps}fps" if fps and fps != "auto" else ""
    suffix = f"_{ratio_tag}" if ratio_tag else ""
    if fps_tag:
        suffix += f"_{fps_tag}"
    out_path = os.path.join(base_dir, f"{base_name}{suffix}.mp4")

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", input_path]

    vf_filters = []
    if ratio in ("9:16", "916"):
        vf_filters.append("crop=ih*9/16:ih,scale=1080:1920")
    elif ratio in ("3:4", "34"):
        vf_filters.append("crop=ih*3/4:ih,scale=810:1080")
    elif ratio in ("1:1", "11"):
        vf_filters.append("crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080")

    if vf_filters:
        cmd.extend(["-vf", ",".join(vf_filters)])

    if fps in ("60", "30"):
        cmd.extend(["-r", fps])

    cmd.extend([
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-threads", "0",
        out_path
    ])

    subprocess.run(cmd, check=True)
    return out_path


# Request models
class InfoRequest(BaseModel):
    url: str


class ProcessRequest(BaseModel):
    url: str
    action: str  # "type_yt_ai_clip", "type_yt_video", "type_yt_short", "type_yt_mp3", "type_yt_clip", "type_ig_reels", "type_ig_ai_clip", "type_tt_video", "type_tt_mp3"
    num_clips: int = 5
    aspect_ratio: str = "9:16"
    use_face_detect: bool = False
    quality: str = "1080"
    fps: Optional[str] = "auto"
    start_time: str = "00:00"
    end_time: str = "00:30"
    segments: Optional[List[Dict[str, str]]] = None
    workspace_name: Optional[str] = "Workspace 01"


class RenameProjectRequest(BaseModel):
    new_name: str


class OpenFileRequest(BaseModel):
    file_path: str


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return HTMLResponse("<h1>Templates not found.</h1>", status_code=404)


@app.get("/guide", response_class=HTMLResponse)
async def guide_page():
    html_path = os.path.join(TEMPLATES_DIR, "guide.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return HTMLResponse("<h1>Guide page not found.</h1>", status_code=404)



@app.post("/api/info")
async def api_info(req: InfoRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    if not is_safe_external_url(url):
        raise HTTPException(status_code=400, detail="URL is invalid or not allowed")

    platform = detect_platform(url)
    fast_title = None
    fast_thumb = None
    fast_duration = 0

    # 1. Fast path: YouTube Innertube + oEmbed (sub-second to ~1.3s)
    if platform == "youtube":
        yt_m = re.search(r'(?:youtu\.be\/|youtube\.com\/(?:shorts\/|watch\?v=|embed\/|v\/|live\/))([a-zA-Z0-9_-]{11})', url)
        if yt_m:
            vid_id = yt_m.group(1)
            fast_thumb = f"https://i.ytimg.com/vi/{vid_id}/maxresdefault.jpg"

            def _fetch_yt_fast():
                t, d, th, ch = None, 0, None, None
                # Method A: Innertube player API (gets accurate lengthSeconds + full title + author)
                try:
                    payload = {
                        "context": {
                            "client": {
                                "clientName": "WEB",
                                "clientVersion": "2.20240101.00.00"
                            }
                        },
                        "videoId": vid_id
                    }
                    r = requests.post(
                        "https://www.youtube.com/youtubei/v1/player",
                        json=payload,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                        timeout=3.0
                    )
                    if r.status_code == 200:
                        vd = r.json().get("videoDetails", {})
                        t = vd.get("title")
                        d = int(vd.get("lengthSeconds") or 0)
                        ch = vd.get("author")
                        thumbs = vd.get("thumbnail", {}).get("thumbnails", [])
                        if thumbs:
                            th = thumbs[-1].get("url")
                except Exception:
                    pass

                # Method B: oEmbed fallback for title/thumb/author if Innertube didn't get title
                if not t or not ch:
                    try:
                        r = requests.get(
                            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid_id}&format=json",
                            timeout=2.0
                        )
                        if r.status_code == 200:
                            odata = r.json()
                            t = t or odata.get("title")
                            ch = ch or odata.get("author_name")
                            if odata.get("thumbnail_url"):
                                th = th or odata["thumbnail_url"]
                    except Exception:
                        pass

                # Method C: Watch page HTML regex fallback for lengthSeconds if d == 0
                if d == 0:
                    try:
                        r = requests.get(
                            f"https://www.youtube.com/watch?v={vid_id}",
                            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                            timeout=2.5
                        )
                        if r.status_code == 200:
                            m_len = re.search(r'\"lengthSeconds\":\"(\d+)\"', r.text)
                            if m_len:
                                d = int(m_len.group(1))
                            if not t:
                                m_title = re.search(r'\"title\":\"([^\"]+)\"', r.text)
                                if m_title:
                                    t = m_title.group(1)
                            if not ch:
                                m_author = re.search(r'\"author\":\"([^\"]+)\"', r.text)
                                if m_author:
                                    ch = m_author.group(1)
                    except Exception:
                        pass

                return t, d, th, ch

            fast_title, fast_duration, yt_thumb, fast_channel = await asyncio.to_thread(_fetch_yt_fast)
            if yt_thumb:
                fast_thumb = yt_thumb

            # If fast path succeeded with both title and duration, return immediately!
            if fast_title and fast_duration > 0:
                return {
                    "title": fast_title,
                    "duration": fast_duration,
                    "thumbnail": fast_thumb,
                    "platform": platform,
                    "channel": fast_channel or "YouTube",
                }

    elif platform == "tiktok":
        try:
            def _fetch_tt():
                r = requests.get(f"https://www.tiktok.com/oembed?url={requests.utils.quote(url)}", timeout=2.5)
                return r.json() if r.status_code == 200 else None
            odata = await asyncio.to_thread(_fetch_tt)
            if odata and "title" in odata:
                fast_title = odata["title"]
                fast_channel = odata.get("author_name") or "TikTok"
                if odata.get("thumbnail_url"):
                    fast_thumb = odata["thumbnail_url"]
        except Exception:
            pass

    # 2. Extract full info with yt-dlp asynchronously if duration is still missing
    def _extract_ydl():
        opts = get_ytdl_base_opts({"skip_download": True, "noplaylist": True})
        opts["socket_timeout"] = 6
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        ydl_task = asyncio.to_thread(_extract_ydl)
        timeout_sec = 8.0
        info = await asyncio.wait_for(ydl_task, timeout=timeout_sec)
        dur = info.get("duration") or fast_duration or 0
        return {
            "title": info.get("title") or fast_title or "Video",
            "duration": dur,
            "thumbnail": info.get("thumbnail") or fast_thumb,
            "platform": platform,
            "channel": info.get("channel") or info.get("uploader") or fast_channel or "YouTube",
        }
    except Exception as e:
        if fast_title:
            return {
                "title": fast_title,
                "duration": fast_duration,
                "thumbnail": fast_thumb,
                "platform": platform,
            }
        return {
            "title": "Media Item",
            "duration": fast_duration,
            "thumbnail": fast_thumb,
            "platform": platform,
            "warning": str(e)
        }


@app.get("/api/check-transcript")
async def api_check_transcript(url: str = Query(...)):
    """Check if YouTube video has native transcript/subtitles in < 0.5s."""
    if not url or not is_safe_external_url(url):
        raise HTTPException(status_code=400, detail="URL is invalid or not allowed")
    try:
        from shorts_generator.local.downloader import _extract_youtube_video_id
        vid = _extract_youtube_video_id(url)
        if not vid:
            return {"has_transcript": True, "provider": "Groq Cloud Whisper"}

        def _check_api():
            try:
                from youtube_transcript_api import YouTubeTranscriptApi
                api = YouTubeTranscriptApi()
                t_list = api.list(vid)
                return len(list(t_list)) > 0
            except Exception:
                return False

        has_t = await asyncio.to_thread(_check_api)
        return {
            "has_transcript": has_t,
            "provider": "YouTube Subtitle Scraper" if has_t else "Groq Cloud Whisper",
            "note": "Official YouTube transcript is available" if has_t else "No official transcript is available; using AI speech-to-text"
        }
    except Exception as e:
        return {"has_transcript": True, "provider": "Groq Cloud Whisper"}


def _save_single_media_to_vault(
    file_path: str,
    category_key: str,
    action: str,
    platform: str,
    prefix: str = "",
    custom_title: Optional[str] = None,
    extra_meta: Optional[Dict] = None,
) -> Optional[Dict]:
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        target_vault_dir = get_category_folder(category_key)
        filename = os.path.basename(file_path)
        title_clean, ext = os.path.splitext(filename)
        vault_filename = format_media_filename(
            custom_title or title_clean,
            ext,
            prefix=prefix,
        )
        vault_file_path = os.path.join(target_vault_dir, vault_filename)
        if os.path.abspath(file_path) != os.path.abspath(vault_file_path):
            shutil.copy2(file_path, vault_file_path)

        storage_root_path = get_storage_root()
        rel = os.path.relpath(vault_file_path, storage_root_path).replace("\\", "/")
        cat_folder = CATEGORY_MAP.get(category_key, category_key)

        vault_item = {
            "id": f"{platform[:2]}_{uuid.uuid4().hex[:8]}",
            "title": custom_title or title_clean,
            "filename": vault_filename,
            "file_path": os.path.abspath(vault_file_path),
            "url": f"/media-vault/{rel}",
            "platform": platform,
            "category": cat_folder,
            "action": action,
            "file_size": os.path.getsize(vault_file_path),
        }
        if extra_meta:
            vault_item.update(extra_meta)

        save_media_metadata(target_vault_dir, vault_item)
        return vault_item
    except Exception as e:
        print(f"[Vault Error] {e}", flush=True)
        return None


def _save_project_to_vault(
    workspace_name: str,
    action: str,
    platform: str,
    source_title: str,
    files_to_save: List[Dict[str, Any]],
    source_url: Optional[str] = None,
    channel: Optional[str] = None,
    transcribe_provider: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Save all generated media files for a workspace into its dedicated folder,
    and persist project metadata with file list in meta.json.
    If workspace already exists, append new files to it without creating duplicates.
    """
    if not files_to_save:
        return None
    try:
        ws_name = (workspace_name or "Workspace 01").strip()
        
        # Check if an existing project with this name already exists in vault
        all_existing_projects = list_vault_projects()
        matched_proj = next(
            (p for p in all_existing_projects if (p.get("workspace_name") or "").strip().lower() == ws_name.lower()),
            None
        )
        
        if matched_proj and matched_proj.get("folder_path") and os.path.exists(matched_proj.get("folder_path")):
            target_vault_dir = matched_proj["folder_path"]
        else:
            target_vault_dir = get_workspace_folder(action, ws_name)

        storage_root_path = get_storage_root()

        saved_files = []
        for item in files_to_save:
            src_path = item.get("file_path")
            if src_path and os.path.exists(src_path):
                fname = os.path.basename(src_path)
                dst_path = os.path.join(target_vault_dir, fname)
                if os.path.abspath(src_path) != os.path.abspath(dst_path):
                    shutil.copy2(src_path, dst_path)
                rel = os.path.relpath(dst_path, storage_root_path).replace("\\", "/")
                file_record = {
                    "id": item.get("id") or f"f_{uuid.uuid4().hex[:8]}",
                    "title": item.get("title") or fname,
                    "filename": fname,
                    "file_path": os.path.abspath(dst_path),
                    "url": f"/media-vault/{rel}",
                    "file_size": os.path.getsize(dst_path),
                    "type": item.get("type", "video"),
                    "platform": platform,
                    "action": action,
                }
                for extra_k in ["score", "caption", "start_time", "end_time", "quality", "aspect_ratio"]:
                    if extra_k in item:
                        file_record[extra_k] = item[extra_k]
                saved_files.append(file_record)

        if not saved_files:
            return None

        # Check existing meta.json in target directory to merge
        existing_meta_path = os.path.join(target_vault_dir, "meta.json")
        existing_record = None
        if os.path.exists(existing_meta_path):
            try:
                with open(existing_meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                        existing_record = data[0]
                    elif isinstance(data, dict):
                        existing_record = data
            except Exception:
                existing_record = None

        if existing_record:
            combined_files = existing_record.get("files", [])
            existing_fnames = {f.get("filename") for f in combined_files if f.get("filename")}
            for sf in saved_files:
                if sf.get("filename") not in existing_fnames:
                    combined_files.append(sf)
            existing_record["files"] = combined_files
            existing_record["updated_at"] = time.time()
            if ws_name:
                existing_record["workspace_name"] = ws_name
            if not existing_record.get("source_title") and source_title:
                existing_record["source_title"] = source_title
            if source_url:
                existing_record["source_url"] = source_url
            if channel:
                existing_record["channel"] = channel
            if transcribe_provider:
                existing_record["transcribe_provider"] = transcribe_provider
            if aspect_ratio:
                existing_record["aspect_ratio"] = aspect_ratio
            project_record = existing_record
        else:
            project_record = {
                "project_id": (matched_proj.get("project_id") if matched_proj else None) or f"proj_{uuid.uuid4().hex[:8]}",
                "workspace_name": ws_name,
                "platform": platform,
                "action": action,
                "source_title": source_title or ws_name,
                "source_url": source_url,
                "channel": channel,
                "transcribe_provider": transcribe_provider,
                "aspect_ratio": aspect_ratio or "9:16",
                "created_at": time.time(),
                "folder_path": os.path.abspath(target_vault_dir),
                "files": saved_files,
            }

        save_project_metadata(target_vault_dir, project_record)
        return project_record
    except Exception as e:
        print(f"[Vault Project Save Error] {e}", flush=True)
        return None


def _worker_process(job_id: str, req: ProcessRequest):
    if jobs.get(job_id, {}).get("cancelled"):
        return

    job_output_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_output_dir, exist_ok=True)

    # Sanitize LOCAL_OUTPUT_DIR in environment in case of stale/corrupted env value
    current_local_out = os.environ.get("LOCAL_OUTPUT_DIR", "output")
    if "=" in current_local_out or not current_local_out.strip():
        os.environ["LOCAL_OUTPUT_DIR"] = "output"
    url = req.url.strip()
    platform = detect_platform(url)
    action = req.action
    ws_name = req.workspace_name or "Workspace 01"

    progress_hook = create_progress_hook(job_id)
    jobs[job_id]["progress"] = 0.0
    jobs[job_id]["download_speed"] = ""
    jobs[job_id]["download_eta"] = ""
    jobs[job_id]["download_frags"] = ""

    try:
        jobs[job_id]["status"] = "processing"

        if action in ("type_yt_ai_clip", "type_ig_ai_clip", "ai_clip"):
            jobs[job_id]["stage"] = "downloading"
            jobs[job_id]["logs"].append("Downloading source video...")

            def on_status(stage: str):
                if jobs.get(job_id, {}).get("cancelled"):
                    raise RuntimeError("CANCELLED_BY_USER")
                jobs[job_id]["stage"] = stage
                jobs[job_id]["logs"].append(f"Stage: {stage}")
                if stage in ("downloading", "queued"):
                    jobs[job_id]["progress"] = 20.0
                elif stage == "checking_transcript":
                    jobs[job_id]["progress"] = 30.0
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "Checking YouTube captions..."
                elif stage == "transcript_found":
                    jobs[job_id]["progress"] = 50.0
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "YouTube transcript found"
                elif stage == "transcribing_groq":
                    jobs[job_id]["progress"] = 40.0
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "Transcribing audio with Groq Cloud Whisper..."
                elif stage == "transcribing_local":
                    jobs[job_id]["progress"] = 40.0
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "Transcribing audio with local Faster-Whisper..."
                elif stage in ("transcribing", "extracting_audio", "uploading"):
                    jobs[job_id]["progress"] = 35.0
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "Extracting and transcribing audio..."
                elif stage in ("ranking_highlights", "detecting_highlights"):
                    jobs[job_id]["progress"] = 65.0
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "Analyzing viral potential and clip moments..."
                elif stage.startswith("rendering_"):
                    parts = stage.split("_")
                    if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                        done_c = int(parts[1])
                        tot_c = int(parts[2])
                        pct = 68.0 + (done_c / max(tot_c, 1)) * 27.0
                        jobs[job_id]["progress"] = round(pct, 1)
                        jobs[job_id]["stage_detail"] = f"Rendering clip {done_c}/{tot_c} (AMD AMF)"
                    jobs[job_id]["stage"] = "rendering"
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                elif stage in ("clipping", "rendering"):
                    jobs[job_id]["progress"] = 70.0
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "Rendering 9:16 clips (vertical crop)..."
                elif stage == "saving":
                    jobs[job_id]["progress"] = 96.0
                    jobs[job_id]["stage_detail"] = "Saving to Media Vault..."
                elif stage == "done":
                    jobs[job_id]["progress"] = 100.0
                    jobs[job_id]["stage_detail"] = "Complete"

            result = generate_shorts(
                youtube_url=url,
                num_clips=req.num_clips,
                aspect_ratio=req.aspect_ratio,
                download_format="1080",
                language=None,
                mode="local",
                use_face_detect=req.use_face_detect,
                on_status=on_status,
                out_dir=job_output_dir,
                progress_hook=progress_hook,
            )

            if jobs.get(job_id, {}).get("cancelled"):
                return

            shorts_list = result.get("shorts", [])
            cleaned_shorts = []
            for s in shorts_list:
                clip_path = s.get("clip_url")
                if clip_path and os.path.exists(clip_path):
                    filename = os.path.basename(clip_path)
                    web_url = f"/output/{job_id}/{filename}"
                    score = s.get("score", 0)
                    caption = clean_caption(str(s.get("caption") or s.get("title") or ""))
                    cleaned_shorts.append({
                        "type": "video",
                        "title": s.get("title", "Highlight"),
                        "start_time": s.get("start_time"),
                        "end_time": s.get("end_time"),
                        "score": score,
                        "caption": caption,
                        "url": web_url,
                        "filename": filename,
                        "download_url": f"/api/download-file/{job_id}/{filename}",
                    })

            jobs[job_id]["results"] = cleaned_shorts
            jobs[job_id]["stage"] = "saving"
            jobs[job_id]["progress"] = 96.0

            # Register AI clips to Media Vault as Project & individual files
            try:
                source_title = "AI Shorts"
                if isinstance(result, dict) and result.get("title"):
                    source_title = result["title"]
                elif shorts_list and shorts_list[0].get("title"):
                    source_title = shorts_list[0]["title"]

                files_for_proj = []
                for s in shorts_list:
                    clip_path = s.get("clip_url")
                    if clip_path and os.path.exists(clip_path):
                        files_for_proj.append({
                            "file_path": clip_path,
                            "title": s.get("title", "Highlight"),
                            "type": "video",
                            "score": s.get("score", 0),
                            "caption": clean_caption(str(s.get("caption") or s.get("title") or "")),
                            "start_time": s.get("start_time"),
                            "end_time": s.get("end_time"),
                            "aspect_ratio": req.aspect_ratio,
                        })

                saved_proj = _save_project_to_vault(
                    workspace_name=ws_name,
                    action=action,
                    platform=platform if platform != "unknown" else "youtube",
                    source_title=source_title,
                    files_to_save=files_for_proj,
                    source_url=url,
                    channel=result.get("channel") if isinstance(result, dict) else None,
                    transcribe_provider=result.get("transcribe_provider") if isinstance(result, dict) else None,
                    aspect_ratio=req.aspect_ratio,
                )
                if saved_proj:
                    jobs[job_id]["project_id"] = saved_proj.get("project_id")
                    jobs[job_id]["workspace_name"] = saved_proj.get("workspace_name")
                jobs[job_id]["logs"].append(f"Saved to Media Vault ({ws_name}).")
            except Exception as v_err:
                print(f"[Vault AI Clips Error] {v_err}", flush=True)
                jobs[job_id]["logs"].append(f"Media Vault warning: {v_err}")

            jobs[job_id]["status"] = "completed"
            jobs[job_id]["stage"] = "done"
            jobs[job_id]["progress"] = 100.0

        elif action in ("type_yt_video", "type_yt_short"):
            if jobs.get(job_id, {}).get("cancelled"):
                return
            jobs[job_id]["stage"] = "downloading"
            jobs[job_id]["logs"].append(f"Downloading YouTube video ({req.quality}p)...")

            file_path = download_youtube_video(url, job_output_dir, req.quality, progress_hook=progress_hook)
            if jobs.get(job_id, {}).get("cancelled"):
                return

            if action == "type_yt_video" and (req.aspect_ratio != "original" or (req.fps and req.fps != "auto")):
                jobs[job_id]["stage"] = "rendering"
                jobs[job_id]["logs"].append(f"Converting video to {req.aspect_ratio} aspect ratio ({req.fps or 'auto'} FPS)...")
                try:
                    file_path = format_video_target(file_path, ratio=req.aspect_ratio, fps=req.fps or "auto")
                except Exception as fmt_err:
                    print(f"[Format Video Error] {fmt_err}", flush=True)
                    jobs[job_id]["logs"].append(f"Format conversion warning: {fmt_err}")

            filename = os.path.basename(file_path)

            jobs[job_id]["results"] = [{
                "type": "video",
                "title": filename,
                "url": f"/output/{job_id}/{filename}",
                "filename": filename,
                "download_url": f"/api/download-file/{job_id}/{filename}",
            }]

            jobs[job_id]["stage"] = "saving"
            jobs[job_id]["progress"] = 95.0

            # Register to Media Vault
            try:
                saved_proj = _save_project_to_vault(
                    workspace_name=ws_name,
                    action=action,
                    platform="youtube",
                    source_title=filename,
                    files_to_save=[{"file_path": file_path, "title": filename, "type": "video", "quality": req.quality}],
                )
                if saved_proj:
                    jobs[job_id]["project_id"] = saved_proj.get("project_id")
                    jobs[job_id]["workspace_name"] = saved_proj.get("workspace_name")
                _save_single_media_to_vault(
                    file_path=file_path,
                    category_key="youtube_video",
                    action=action,
                    platform="youtube",
                    prefix=f"{req.quality}p" if req.quality else "",
                    extra_meta={"quality": req.quality},
                )
                jobs[job_id]["logs"].append(f"Saved to Media Vault ({ws_name}).")
            except Exception as v_err:
                print(f"[Vault Error] {v_err}", flush=True)
                jobs[job_id]["logs"].append(f"Media Vault warning: {v_err}")

            jobs[job_id]["status"] = "completed"
            jobs[job_id]["stage"] = "done"
            jobs[job_id]["progress"] = 100.0

        elif action in ("type_ig_reels", "ig_reels"):
            if jobs.get(job_id, {}).get("cancelled"):
                return
            jobs[job_id]["stage"] = "downloading"
            jobs[job_id]["logs"].append("Downloading Instagram Reel (full quality)...")

            file_path = download_instagram_reels(url, job_output_dir, progress_hook=progress_hook)
            if jobs.get(job_id, {}).get("cancelled"):
                return
            filename = os.path.basename(file_path)

            jobs[job_id]["results"] = [{
                "type": "video",
                "title": filename,
                "url": f"/output/{job_id}/{filename}",
                "filename": filename,
                "download_url": f"/api/download-file/{job_id}/{filename}",
            }]

            jobs[job_id]["stage"] = "saving"
            jobs[job_id]["progress"] = 95.0

            # Register to Media Vault
            try:
                saved_proj = _save_project_to_vault(
                    workspace_name=ws_name,
                    action=action,
                    platform="instagram",
                    source_title=filename,
                    files_to_save=[{"file_path": file_path, "title": filename, "type": "video"}],
                )
                if saved_proj:
                    jobs[job_id]["project_id"] = saved_proj.get("project_id")
                    jobs[job_id]["workspace_name"] = saved_proj.get("workspace_name")
                _save_single_media_to_vault(
                    file_path=file_path,
                    category_key="instagram_video",
                    action=action,
                    platform="instagram",
                )
                jobs[job_id]["logs"].append(f"Saved to Media Vault ({ws_name}).")
            except Exception as v_err:
                print(f"[Vault Error] {v_err}", flush=True)
                jobs[job_id]["logs"].append(f"Media Vault warning: {v_err}")

            jobs[job_id]["status"] = "completed"
            jobs[job_id]["stage"] = "done"
            jobs[job_id]["progress"] = 100.0

        elif action in ("type_tt_video", "tt_video"):
            if jobs.get(job_id, {}).get("cancelled"):
                return
            jobs[job_id]["stage"] = "downloading"
            jobs[job_id]["logs"].append("Downloading TikTok video (no watermark)...")

            file_path = download_tiktok_video(url, job_output_dir, progress_hook=progress_hook)
            if jobs.get(job_id, {}).get("cancelled"):
                return
            filename = os.path.basename(file_path)

            jobs[job_id]["results"] = [{
                "type": "video",
                "title": filename,
                "url": f"/output/{job_id}/{filename}",
                "filename": filename,
                "download_url": f"/api/download-file/{job_id}/{filename}",
            }]

            jobs[job_id]["stage"] = "saving"
            jobs[job_id]["progress"] = 95.0

            # Register to Media Vault
            try:
                saved_proj = _save_project_to_vault(
                    workspace_name=ws_name,
                    action=action,
                    platform="tiktok",
                    source_title=filename,
                    files_to_save=[{"file_path": file_path, "title": filename, "type": "video"}],
                )
                if saved_proj:
                    jobs[job_id]["project_id"] = saved_proj.get("project_id")
                    jobs[job_id]["workspace_name"] = saved_proj.get("workspace_name")
                _save_single_media_to_vault(
                    file_path=file_path,
                    category_key="tiktok_video",
                    action=action,
                    platform="tiktok",
                )
                jobs[job_id]["logs"].append(f"Saved to Media Vault ({ws_name}).")
            except Exception as v_err:
                print(f"[Vault Error] {v_err}", flush=True)
                jobs[job_id]["logs"].append(f"Media Vault warning: {v_err}")

            jobs[job_id]["status"] = "completed"
            jobs[job_id]["stage"] = "done"
            jobs[job_id]["progress"] = 100.0

        elif action in ("type_yt_mp3", "type_tt_mp3", "mp3"):
            if jobs.get(job_id, {}).get("cancelled"):
                return
            jobs[job_id]["stage"] = "downloading"
            jobs[job_id]["logs"].append("Extracting 320 kbps MP3 audio...")

            file_path = download_mp3(url, job_output_dir, progress_hook=progress_hook)
            if jobs.get(job_id, {}).get("cancelled"):
                return
            filename = os.path.basename(file_path)

            jobs[job_id]["results"] = [{
                "type": "audio",
                "title": filename,
                "url": f"/output/{job_id}/{filename}",
                "filename": filename,
                "download_url": f"/api/download-file/{job_id}/{filename}",
            }]

            jobs[job_id]["stage"] = "saving"
            jobs[job_id]["progress"] = 95.0

            # Register to Media Vault
            try:
                saved_proj = _save_project_to_vault(
                    workspace_name=ws_name,
                    action=action,
                    platform=platform if platform != "unknown" else "youtube",
                    source_title=filename,
                    files_to_save=[{"file_path": file_path, "title": filename, "type": "audio"}],
                )
                if saved_proj:
                    jobs[job_id]["project_id"] = saved_proj.get("project_id")
                    jobs[job_id]["workspace_name"] = saved_proj.get("workspace_name")
                _save_single_media_to_vault(
                    file_path=file_path,
                    category_key="youtube_audio",
                    action=action,
                    platform=platform if platform != "unknown" else "youtube",
                    prefix="320kbps",
                )
                jobs[job_id]["logs"].append(f"Saved to Media Vault ({ws_name}).")
            except Exception as v_err:
                print(f"[Vault Error] {v_err}", flush=True)
                jobs[job_id]["logs"].append(f"Media Vault warning: {v_err}")

            jobs[job_id]["status"] = "completed"
            jobs[job_id]["stage"] = "done"
            jobs[job_id]["progress"] = 100.0

        elif action in ("type_yt_clip", "manual_clip"):
            if jobs.get(job_id, {}).get("cancelled"):
                return
            jobs[job_id]["stage"] = "downloading"
            jobs[job_id]["logs"].append("Downloading source video...")

            # Prepare segments
            raw_segments = req.segments or []
            if not raw_segments:
                raw_segments = [{"start_time": req.start_time, "end_time": req.end_time}]

            valid_segments = []
            for s in raw_segments:
                s_start = (s.get("start_time") or "00:00").strip()
                s_end = (s.get("end_time") or "00:30").strip()
                st_s = parse_timestamp(s_start)
                et_s = parse_timestamp(s_end)
                if et_s <= st_s:
                    et_s = st_s + 30.0
                    if et_s >= 3600:
                        s_end = f"{int(et_s // 3600):02d}:{int((et_s % 3600) // 60):02d}:{int(et_s % 60):02d}"
                    else:
                        s_end = f"{int(et_s // 60):02d}:{int(et_s % 60):02d}" 
                valid_segments.append({
                    "start_time": s_start,
                    "end_time": s_end,
                    "start_s": st_s,
                    "end_s": et_s,
                })

            base_opts = {
                "format": "bestvideo[height<=1080]+bestaudio/best",
                "outtmpl": os.path.join(job_output_dir, "full.%(ext)s"),
                "merge_output_format": "mp4",
            }
            if progress_hook:
                base_opts["progress_hooks"] = [progress_hook]
            opts = get_ytdl_base_opts(base_opts)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "video")
                channel = info.get("uploader") or info.get("channel") or ""

            full_path = None
            for ext in ["mp4", "mkv", "webm"]:
                cand = os.path.join(job_output_dir, f"full.{ext}")
                if os.path.exists(cand):
                    full_path = cand
                    break
            if not full_path:
                raise RuntimeError("Downloaded file was not found")

            if jobs.get(job_id, {}).get("cancelled"):
                return

            jobs[job_id]["stage"] = "clipping"
            jobs[job_id]["progress"] = 70.0
            jobs[job_id]["download_speed"] = ""
            jobs[job_id]["download_eta"] = ""

            clean = sanitize_title(title)
            is_multi = len(valid_segments) > 1
            results = []
            files_to_save = []

            for idx, seg in enumerate(valid_segments):
                if jobs.get(job_id, {}).get("cancelled"):
                    return
                st_str = seg["start_time"]
                et_str = seg["end_time"]
                suffix = f"_clip_{idx+1}" if is_multi else "_clip"
                out_filename = f"{clean}{suffix}.mp4"
                out_clip_path = os.path.join(job_output_dir, out_filename)

                jobs[job_id]["logs"].append(f"Trimming segment #{idx+1} ({st_str} - {et_str})...")
                extract_clip_segment(
                    full_path,
                    out_clip_path,
                    seg["start_s"],
                    seg["end_s"],
                    ratio=req.aspect_ratio,
                )

                clip_title = f"Clip #{idx+1} ({st_str} - {et_str})" if is_multi else f"Clip ({st_str} - {et_str})"
                results.append({
                    "type": "video",
                    "title": clip_title,
                    "url": f"/output/{job_id}/{out_filename}",
                    "filename": out_filename,
                    "download_url": f"/api/download-file/{job_id}/{out_filename}",
                    "start_time": st_str,
                    "end_time": et_str,
                    "aspect_ratio": req.aspect_ratio,
                })
                files_to_save.append({
                    "file_path": out_clip_path,
                    "title": clip_title,
                    "type": "video",
                    "start_time": st_str,
                    "end_time": et_str,
                    "aspect_ratio": req.aspect_ratio,
                })

            jobs[job_id]["results"] = results
            jobs[job_id]["stage"] = "saving"
            jobs[job_id]["progress"] = 95.0

            # Register to Media Vault
            try:
                if is_multi:
                    # Multi-clip (> 1): Enter Trim Workspace (Project-based)
                    saved_proj = _save_project_to_vault(
                        workspace_name=ws_name,
                        action=action,
                        platform="youtube",
                        source_title=title,
                        source_url=url,
                        channel=channel,
                        aspect_ratio=req.aspect_ratio,
                        files_to_save=files_to_save,
                    )
                    if saved_proj:
                        jobs[job_id]["project_id"] = saved_proj.get("project_id")
                        jobs[job_id]["workspace_name"] = saved_proj.get("workspace_name")
                    jobs[job_id]["logs"].append(f"Saved to Trim Workspace: {ws_name} ({len(files_to_save)} clips).")
                else:
                    # Single clip (1): Enter standard Media Vault workspace
                    _save_single_media_to_vault(
                        file_path=files_to_save[0]["file_path"],
                        category_key="youtube_video",
                        action=action,
                        platform="youtube",
                        prefix="clip",
                        custom_title=files_to_save[0]["title"],
                    )
                    jobs[job_id]["logs"].append(f"Saved to Media Vault ({ws_name}).")
            except Exception as v_err:
                print(f"[Vault Trimmer Error] {v_err}", flush=True)
                jobs[job_id]["logs"].append(f"Media Vault warning: {v_err}")

            jobs[job_id]["status"] = "completed"
            jobs[job_id]["stage"] = "done"
            jobs[job_id]["progress"] = 100.0

        else:
            raise ValueError(f"Unknown action: {action}")

    except Exception as e:
        if str(e) == "CANCELLED_BY_USER" or jobs.get(job_id, {}).get("cancelled"):
            jobs[job_id]["status"] = "cancelled"
            jobs[job_id]["stage"] = "cancelled"
            jobs[job_id]["logs"].append("Job cancelled by user.")
            return
        import traceback
        traceback.print_exc()
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["logs"].append(f"Error: {str(e)}")


@app.post("/api/process")
async def api_process(req: ProcessRequest, background_tasks: BackgroundTasks):
    if not req.url or not req.url.strip().startswith("http") or not is_safe_external_url(req.url.strip()):
        raise HTTPException(status_code=400, detail="URL is invalid or not allowed")

    _prune_old_jobs(50)
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id,
        "url": req.url.strip(),
        "action": req.action,
        "workspace_name": req.workspace_name or "Workspace 01",
        "status": "queued",
        "stage": "queued",
        "progress": 0.0,
        "download_speed": "",
        "download_eta": "",
        "download_frags": "",
        "cancelled": False,
        "logs": ["Job added to queue..."],
        "results": [],
        "error": None,
    }

    background_tasks.add_task(_worker_process, job_id, req)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/status/{job_id}")
async def api_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/download-file/{job_id}/{filename}")
async def api_download_file(job_id: str, filename: str):
    file_path = _safe_output_file(job_id, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/api/download-zip/{job_id}")
async def api_download_zip(job_id: str):
    if job_id not in jobs or jobs[job_id].get("status") != "completed":
        raise HTTPException(status_code=400, detail="Job is not complete or was not found")

    job_output_dir = _safe_output_job_dir(job_id)
    zip_filename = f"media_{job_id}.zip"
    zip_path = _safe_join(OUTPUT_DIR, zip_filename)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for item in jobs[job_id].get("results", []):
            fname = item.get("filename")
            if fname:
                try:
                    file_full = _safe_output_file(job_id, fname)
                except HTTPException:
                    continue
                if os.path.exists(file_full):
                    zipf.write(file_full, arcname=fname)

    return FileResponse(
        zip_path,
        filename=zip_filename,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'}
    )


@app.post("/api/cancel/{job_id}")
async def api_cancel(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    jobs[job_id]["cancelled"] = True
    jobs[job_id]["status"] = "cancelled"
    jobs[job_id]["stage"] = "cancelled"
    jobs[job_id]["logs"].append("Cancellation triggered by the user.")

    job_output_dir = _safe_output_job_dir(job_id)
    if os.path.exists(job_output_dir):
        try:
            shutil.rmtree(job_output_dir)
        except Exception:
            pass

    return {"status": "cancelled", "job_id": job_id}


# Media vault routes
@app.get("/api/vault")
async def api_get_vault():
    return {
        "items": list_vault_items(),
        "stats": get_storage_stats(),
    }


@app.get("/api/vault/projects")
async def api_get_vault_projects():
    return {
        "projects": list_vault_projects(),
        "stats": get_storage_stats(),
        "next_workspace_index": get_next_workspace_index(),
    }


@app.patch("/api/vault/project/{project_id}/rename")
async def api_rename_vault_project(project_id: str, req: RenameProjectRequest):
    success = rename_vault_project(project_id, req.new_name)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "renamed", "project_id": project_id, "new_name": req.new_name}


@app.delete("/api/vault/project/{project_id}")
async def api_delete_vault_project(project_id: str):
    success = delete_vault_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "deleted", "project_id": project_id}


@app.delete("/api/vault/{item_id}")
async def api_delete_vault(item_id: str):
    success = delete_vault_item(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found in Media Vault")
    return {"status": "deleted", "item_id": item_id}


@app.post("/api/vault/open-file")
async def api_vault_open_file(req: OpenFileRequest):
    norm_path = os.path.abspath(os.path.normpath(req.file_path))
    if not os.path.exists(norm_path):
        raise HTTPException(status_code=404, detail="File not found")
    if not _path_is_inside(norm_path, [get_storage_root(), OUTPUT_DIR]):
        raise HTTPException(status_code=400, detail="File is outside the Media Vault")

    if sys.platform == "win32":
        try:
            subprocess.Popen(["explorer.exe", f"/select,{norm_path}"])
        except Exception:
            pass

    return {"status": "success", "file": norm_path}


@app.post("/api/vault/open-folder")
async def api_vault_open_folder(payload: Optional[Dict[str, Any]] = None):
    folder_to_open = None
    if payload and isinstance(payload, dict):
        folder_to_open = payload.get("folder")
    if not folder_to_open or not str(folder_to_open).strip():
        folder_to_open = get_storage_root()

    folder_to_open = os.path.abspath(os.path.normpath(str(folder_to_open).strip()))
    if not _path_is_inside(folder_to_open, [get_storage_root(), OUTPUT_DIR]):
        raise HTTPException(status_code=400, detail="Folder is outside the Media Vault")
    os.makedirs(folder_to_open, exist_ok=True)

    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", folder_to_open])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder_to_open])
        else:
            subprocess.Popen(["xdg-open", folder_to_open])
        return {"status": "success", "folder": folder_to_open}
    except Exception as e:
        logger.error(f"Error opening folder {folder_to_open}: {e}")
        raise HTTPException(status_code=500, detail=f"Could not open folder: {e}")


@app.post("/api/settings/browse-folder")
async def api_browse_folder():
    current_root = get_storage_root()
    selected_path = ""
    try:
        py_cmd = (
            "import ctypes, os, sys\n"
            "try:\n"
            "    ctypes.windll.shcore.SetProcessDpiAwareness(2)\n"
            "except Exception:\n"
            "    try:\n"
            "        ctypes.windll.user32.SetProcessDPIAware()\n"
            "    except Exception:\n"
            "        pass\n"
            "import tkinter as tk, tkinter.filedialog as fd\n"
            "root = tk.Tk()\n"
            "root.withdraw()\n"
            "root.wm_attributes('-topmost', 1)\n"
            f"p = fd.askdirectory(initialdir={repr(current_root)}, title='Select Media Vault Folder')\n"
            "print(p)\n"
        )
        proc = subprocess.run([sys.executable, "-c", py_cmd], capture_output=True, text=True, timeout=120)
        out = proc.stdout.strip()
        if out and os.path.exists(out):
            selected_path = os.path.abspath(out)
    except Exception as e:
        logger.warning(f"Error in browse folder dialog: {e}")

    return {"status": "success" if selected_path else "cancelled", "path": selected_path}


@app.post("/api/settings/check-system")
async def api_check_system():
    has_ffmpeg = bool(shutil.which("ffmpeg") or os.path.exists(r"C:\ffmpeg\bin\ffmpeg.exe"))
    ffmpeg_ver = "Available"
    if has_ffmpeg:
        try:
            res = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
            first_line = res.stdout.splitlines()[0] if res.stdout else ""
            if "version" in first_line.lower():
                parts = first_line.split()
                ffmpeg_ver = parts[2] if len(parts) > 2 else "Available"
        except Exception:
            ffmpeg_ver = "Available"

    ytdlp_ver = str(getattr(yt_dlp.version, "__version__", "Available"))

    try:
        import cv2
        has_opencv = True
        opencv_ver = f"v{cv2.__version__} Active"
    except Exception:
        has_opencv = False
        opencv_ver = "Inactive"

    curr_storage = get_storage_root()
    storage_writable = is_writable(curr_storage)

    cookie_path = os.path.join(BASE_DIR, "cookies.txt")
    has_cookies = os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0
    cookie_size = f"{os.path.getsize(cookie_path) / 1024:.1f} KB" if has_cookies else "0 KB"

    return {
        "status": "success",
        "ffmpeg": has_ffmpeg,
        "ffmpeg_version": ffmpeg_ver,
        "ytdlp": ytdlp_ver,
        "opencv": has_opencv,
        "opencv_version": opencv_ver,
        "storage": storage_writable,
        "storage_path": curr_storage,
        "cookies": {
            "exists": has_cookies,
            "name": "cookies.txt",
            "size": cookie_size,
        },
    }


# Settings routes
class SettingsUpdateRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    storage_dir: Optional[str] = None
    migrate_files: Optional[bool] = False


class TestKeyRequest(BaseModel):
    provider: str
    api_key: str


@app.get("/api/settings")
async def api_get_settings():
    cookie_path = os.path.join(BASE_DIR, "cookies.txt")
    has_cookies = os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0
    cookie_size = f"{os.path.getsize(cookie_path) / 1024:.1f} KB" if has_cookies else "0 KB"

    try:
        import cv2
        has_opencv = True
    except Exception:
        has_opencv = False

    has_ffmpeg = bool(shutil.which("ffmpeg") or os.path.exists(r"C:\ffmpeg\bin\ffmpeg.exe"))
    ytdlp_ver = str(getattr(yt_dlp.version, "__version__", "v2025.02.19"))
    curr_storage = get_storage_root()

    return {
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "groq_api_key": os.getenv("GROQ_API_KEY", ""),
        "groq_model": os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo"),
        "storage_dir": curr_storage,
        "status": {
            "ffmpeg": has_ffmpeg,
            "ytdlp": ytdlp_ver,
            "opencv": has_opencv,
            "storage": is_writable(curr_storage),
            "cookies": {
                "exists": has_cookies,
                "name": "cookies.txt",
                "size": cookie_size,
            },
        },
    }


@app.post("/api/settings")
async def api_save_settings(req: SettingsUpdateRequest):
    updates = {}
    if req.gemini_api_key is not None:
        updates["GEMINI_API_KEY"] = req.gemini_api_key.strip()
    if req.groq_api_key is not None:
        updates["GROQ_API_KEY"] = req.groq_api_key.strip()

    migrated_info = None
    if req.storage_dir is not None and req.storage_dir.strip():
        norm_dir = os.path.abspath(req.storage_dir.strip())
        if not is_writable(norm_dir):
            raise HTTPException(status_code=400, detail="Storage directory is inaccessible or not writable.")

        old_dir = get_storage_root()
        if req.migrate_files or os.path.abspath(old_dir) != os.path.abspath(norm_dir):
            import storage_manager
            try:
                migrated_info = storage_manager.migrate_storage(old_dir, norm_dir)
            except Exception as e:
                logger.error(f"Error migrating storage: {e}")
                raise HTTPException(status_code=500, detail=f"Could not move files: {e}")

        updates["MEDIA_STORAGE_DIR"] = norm_dir
        os.environ["MEDIA_STORAGE_DIR"] = norm_dir

    _update_env_file(updates)
    return {
        "status": "saved",
        "storage_dir": get_storage_root(),
        "migrated": migrated_info,
        "stats": get_storage_stats(),
    }


def _update_env_file(updates: dict):
    env_path = os.path.join(BASE_DIR, ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _ = stripped.split("=", 1)
            k = k.strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}\n")
                updated_keys.add(k)
                os.environ[k] = str(updates[k])
                continue
        if not line.endswith("\n"):
            line += "\n"
        new_lines.append(line)

    for k, v in updates.items():
        if k not in updated_keys:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"
            new_lines.append(f"{k}={v}\n")
            os.environ[k] = str(v)

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


@app.post("/api/settings/test-key")
async def api_test_key(req: TestKeyRequest):
    provider = req.provider.lower()
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")

    if provider == "gemini":
        try:
            resp = requests.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                timeout=8,
            )
            if resp.status_code == 200:
                _update_env_file({"GEMINI_API_KEY": key})
                return {"valid": True, "message": "200 OK", "saved": True}
            else:
                return {"valid": False, "message": f"{resp.status_code} Error"}
        except Exception as e:
            return {"valid": False, "message": str(e)[:40]}

    elif provider == "groq":
        try:
            resp = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=8,
            )
            if resp.status_code == 200:
                _update_env_file({"GROQ_API_KEY": key})
                return {"valid": True, "message": "200 OK", "saved": True}
            else:
                return {"valid": False, "message": f"{resp.status_code} Error"}
        except Exception as e:
            return {"valid": False, "message": str(e)[:40]}

    return {"valid": False, "message": "Unknown provider"}


class CookieUploadRequest(BaseModel):
    filename: Optional[str] = "cookies.txt"
    content: str


@app.post("/api/settings/upload-cookies")
async def api_upload_cookies(req: CookieUploadRequest):
    cookie_path = os.path.join(BASE_DIR, "cookies.txt")
    with open(cookie_path, "w", encoding="utf-8") as f:
        f.write(req.content)
    size_kb = f"{len(req.content.encode('utf-8')) / 1024:.1f} KB"
    return {"status": "uploaded", "filename": req.filename or "cookies.txt", "size": size_kb}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="localhost", port=8000, reload=True)
