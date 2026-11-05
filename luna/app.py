# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

import asyncio
import copy
from contextlib import asynccontextmanager
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import ipaddress
import tempfile
import time
import urllib.parse
import uuid
import zipfile
from typing import Any, Callable, Dict, List, Literal, Optional

import requests
import yt_dlp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(PACKAGE_DIR)

# Load environment variables
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Ensure ffmpeg in PATH
os.environ["PATH"] += os.pathsep + r"C:\ffmpeg\bin"

from .ffmpeg_setup import ensure_ffmpeg

ensure_ffmpeg()

from .clipper import generate_shorts
from .clipper.config import (
    DEFAULT_OPENAI_BASE_URL,
    openai_base_url,
    openai_model,
    transcribe_provider,
    transcribe_provider_label,
)
from .clipper.highlights import clean_caption
from .storage_manager import (
    CATEGORY_MAP,
    get_storage_root,
    get_category_folder,
    get_workspace_folder,
    format_media_filename,
    invalidate_storage_root_cache,
    is_writable,
    sanitize_name,
)
from .vault_service import (
    save_media_metadata,
    save_project_metadata,
    list_vault_items,
    list_vault_projects,
    rename_vault_project,
    delete_vault_project,
    get_next_workspace_index,
    delete_vault_item,
    get_storage_stats,
    workspace_name_taken,
)

OUTPUT_DIR = os.path.join(BASE_DIR, "output")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(PACKAGE_DIR, "templates")
ASSETS_DIR = os.path.join(PACKAGE_DIR, "assets")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)

logger = logging.getLogger(__name__)


def _cli_value(flag: str) -> Optional[str]:
    """Read --flag value from argv, for uvicorn started with explicit flags."""
    argv = sys.argv
    for index, item in enumerate(argv):
        if item == flag and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith(flag + "="):
            return item.split("=", 1)[1]
    return None


def _startup_banner() -> str:
    """Human-readable URL line printed once the server is ready.

    Uvicorn reports the bind address (127.0.0.1), which reads as a different site to
    people who typed localhost. Both work, so show both. CLI flags win over env vars,
    matching how uvicorn was invoked.
    """
    port = (_cli_value("--port") or os.getenv("LUNA_PORT", "8000")).strip() or "8000"
    host = (_cli_value("--host") or os.getenv("LUNA_HOST", "127.0.0.1")).strip().lower() or "127.0.0.1"
    if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "::"):
        return f"Luna is running: http://127.0.0.1:{port}  or  http://localhost:{port}"
    return f"Luna is running: http://{host}:{port}  (or http://localhost:{port} if it is the same machine)"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # "uvicorn.error" is where uvicorn's own startup lines go, so the banner lands in
    # the same stream and ordering. In tests (no uvicorn logging config) INFO is
    # dropped by the root logger, so the suite stays quiet.
    logging.getLogger("uvicorn.error").info(_startup_banner())
    restored = _restore_jobs()
    if restored:
        logger.info(f"Restored {restored} job(s) from {OUTPUT_DIR}")
    stop = threading.Event()
    threading.Thread(target=_persist_jobs_loop, args=(stop,), daemon=True, name="luna-job-saver").start()
    yield
    stop.set()


app = FastAPI(
    title="Luna: Multi-Platform Media & AI Shorts Web Studio",
    lifespan=_lifespan,
)


def allowed_hosts() -> List[str]:
    """Host headers Luna answers to. Anything else is rejected, which blocks DNS rebinding."""
    extra = [h.strip() for h in os.getenv("LUNA_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return ["localhost", "127.0.0.1", "[::1]", *extra]


app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())

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

# Cancellation is kept outside the job dict: a threading.Event cannot be JSON-encoded
# or deep-copied, and /api/status copies the dict while the worker mutates it.
job_cancel_events: Dict[str, threading.Event] = {}
job_finished: set = set()
# The request each job was started with, so a failed job can be retried after a restart.
job_requests: Dict[str, Dict] = {}

JOB_FILE = "job.json"
INTERRUPTED_ERROR = "Interrupted by a server restart. Retry to continue from what was already downloaded."


def _save_job(job_id: str) -> None:
    """Write output/<job>/job.json. Write-then-rename, so a crash never leaves half a file."""
    job = jobs.get(job_id)
    if job is None:
        return
    folder = os.path.join(OUTPUT_DIR, job_id)
    try:
        data = json.dumps({"job": copy.deepcopy(job), "request": job_requests.get(job_id)})
    except RuntimeError:
        return  # the worker changed the dict mid-copy; the next save picks it up
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, JOB_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, os.path.join(folder, JOB_FILE))


def _persist_jobs_loop(stop: threading.Event, interval: float = 2.0) -> None:
    """Save running jobs every few seconds; the worker saves the final state itself."""
    while not stop.wait(interval):
        for job_id in list(jobs):
            job = jobs.get(job_id) or {}
            if job_id in job_finished or job.get("cancelled"):
                continue
            try:
                _save_job(job_id)
            except OSError as e:
                logger.warning(f"Could not save job {job_id}: {e}")


def _restore_jobs() -> int:
    """Load saved jobs. Anything still queued or running died with the old process."""
    restored = 0
    saved = []
    try:
        for name in os.listdir(OUTPUT_DIR):
            path = os.path.join(OUTPUT_DIR, name, JOB_FILE)
            if re.fullmatch(r"[0-9a-f]{8}", name) and name not in jobs and os.path.isfile(path):
                saved.append((os.path.getmtime(path), name, path))
    except OSError:
        return 0
    # Oldest first, so _prune_old_jobs evicts in age order as it does for live jobs.
    for _, name, path in sorted(saved):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        job = data.get("job") if isinstance(data, dict) else None
        if not isinstance(job, dict) or job.get("id") != name:
            continue
        interrupted = job.get("status") in ("queued", "processing")
        if interrupted:
            job.update(status="failed", error=INTERRUPTED_ERROR, download_speed="", download_eta="")
            job.setdefault("logs", []).append(f"Error: {INTERRUPTED_ERROR}")
        jobs[name] = job
        if isinstance(data.get("request"), dict):
            job_requests[name] = data["request"]
        job_finished.add(name)
        if interrupted:
            try:
                _save_job(name)
            except OSError:
                pass
        restored += 1
    return restored


def _cleanup_job_output(job_id: str) -> None:
    """Remove the temporary output folder for a job (vault copies are untouched)."""
    folder = os.path.join(OUTPUT_DIR, job_id)
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)


def _prune_old_jobs(max_keep: int = 50):
    """Drop the oldest terminal jobs once the registry grows past max_keep.

    Only jobs whose worker has already returned are eligible: a cancelled job can
    still be encoding, and evicting it used to raise KeyError inside the worker.
    """
    if len(jobs) <= max_keep:
        return
    terminal_keys = [
        k for k, v in jobs.items()
        if v.get("status") in ("completed", "failed", "cancelled") and k in job_finished
    ]
    for k in terminal_keys:
        if len(jobs) <= max_keep:
            break
        jobs.pop(k, None)
        job_cancel_events.pop(k, None)
        job_requests.pop(k, None)
        job_finished.discard(k)
        _cleanup_job_output(k)


def cleanup_expired_jobs(max_age_days: int = 30) -> int:
    """Delete output/<job> folders older than max_age_days that no live job owns.

    Media Vault keeps its own copy of everything that was saved, so these folders are
    only the transient working copies. Only 8-hex job ids are touched.
    """
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    try:
        entries = os.listdir(OUTPUT_DIR)
    except OSError:
        return 0
    for name in entries:
        if not re.fullmatch(r"[0-9a-f]{8}", name):
            continue
        path = os.path.join(OUTPUT_DIR, name)
        if not os.path.isdir(path) or name in jobs:
            continue
        try:
            if os.path.getmtime(path) >= cutoff:
                continue
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    if removed:
        logger.info(f"Removed {removed} expired job folder(s) from {OUTPUT_DIR}")
    return removed


def external_url_problem(url: str) -> Optional[str]:
    """Return a user-facing reason a URL is not allowed, or None when it is fine.

    Rejects hosts that resolve to a non-public address (SSRF prevention) and tells
    the difference between "that address is blocked" and "the network is down",
    which used to collapse into the misleading "URL is invalid".
    """
    if not url or not isinstance(url, str) or not url.strip():
        return "Enter a video link first."
    url = url.strip()
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return "That link is not a valid URL."
    if parsed.scheme not in ("http", "https"):
        return "The link must start with http:// or https://."
    hostname = parsed.hostname
    if not hostname:
        return "That link has no host name."
    hostname_lower = hostname.lower().strip("[]")
    # yt-dlp would fetch any URL it is given, so only hand it the sites Luna supports.
    if detect_platform(url) == "unknown":
        return "Only YouTube, TikTok and Instagram links are supported."
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return "That link has an invalid port."
    try:
        infos = socket.getaddrinfo(hostname_lower, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return "Could not reach that site. Check your internet connection and try again."
    if not infos:
        return "Could not reach that site. Check your internet connection and try again."
    for info in infos:
        address = str(info[4][0]).split("%")[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return "That address is not allowed."
        if not ip.is_global:
            return "That address is not allowed."
    return None


def is_safe_external_url(url: str) -> bool:
    """True when the URL is http(s) and its host resolves to a public address."""
    return external_url_problem(url) is None


_NETWORK_ERROR_HINTS = (
    "getaddrinfo", "name or service not known", "temporary failure in name resolution",
    "nodename nor servname", "no address associated", "network is unreachable",
    "no route to host", "connection refused", "connection reset", "connection aborted",
    "connection error", "timed out", "urlopen error", "unable to download webpage",
    "unable to download video", "unable to connect", "errno 11001", "errno 10054",
    "errno 10060", "ssl:", "certificate verify failed", "[errno 2] no such file or directory",
)


def friendly_error_message(exc: BaseException) -> str:
    """Translate a technical download/provider error into something the user can act on.

    yt-dlp reports things like "[Errno 2] No such file or directory: ...part-Frag7"
    when the network drops mid-fragment; the raw text tells the user nothing.
    """
    raw = str(exc).strip()
    text = raw.lower()
    if any(hint in text for hint in _NETWORK_ERROR_HINTS):
        return "The download was interrupted. Check your internet connection and try again."
    if "sign in to confirm" in text or "not a bot" in text or "cookies" in text and "sign" in text:
        return "YouTube asked this request to sign in. Upload cookies in Settings, then try again."
    if "private video" in text or "video unavailable" in text or "this video is unavailable" in text:
        return "This video is private, deleted, or blocked in your region."
    if "http error 404" in text or "not found" in text:
        return "The video could not be found. Check the link and try again."
    if "http error 403" in text or "forbidden" in text:
        return "The site refused the download (403). Cookies in Settings may help for this video."
    if "unsupported url" in text:
        return "That link is not a supported video page."
    if "no space left" in text:
        return "The disk is full. Free some space and try again."
    if "permission denied" in text:
        return "Luna could not write to the output folder. Check its permissions."
    if raw:
        return raw[:240]
    return "The job failed for an unknown reason."


# Utilities
def sanitize_title(title: str) -> str:
    """Turn a media title into a safe file stem (reserved names, trailing dots, length)."""
    title = re.sub(r'#\S+', '', str(title or ""))
    cleaned = sanitize_name(title, max_length=80)
    return cleaned or "media"


def parse_timestamp(ts: str) -> float:
    """Parse "HH:MM:SS", "MM:SS" or plain seconds.

    Raises ValueError instead of silently returning 0.0, so a typo in the trim form
    becomes a 400 rather than a clip rendered at the wrong offset.
    """
    raw = str(ts or "").strip()
    if not raw:
        raise ValueError("Timestamp is empty")
    parts = raw.split(":")
    if len(parts) > 3:
        raise ValueError(f"Invalid timestamp: {ts!r}")
    try:
        values = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"Invalid timestamp: {ts!r}")
    for value in values:
        if value < 0:
            raise ValueError(f"Timestamp cannot be negative: {ts!r}")
    for value in values[1:]:
        if value >= 60:
            raise ValueError(f"Minutes and seconds must be below 60: {ts!r}")
    seconds = 0.0
    for value in values:
        seconds = seconds * 60 + value
    return seconds


def _run_ffmpeg(cmd: List[str], timeout_sec: float, cancel_event: Optional[threading.Event] = None) -> None:
    """Run an ffmpeg command, capturing stderr so the failure reason survives.

    The process is polled instead of blocking in subprocess.run so a cancel can
    terminate it, and the timeout keeps a stuck encode from pinning a worker forever.
    """
    deadline = time.time() + max(30.0, timeout_sec)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg was not found. Install FFmpeg or let Luna download it on first run.")

    while True:
        if cancel_event is not None and cancel_event.is_set():
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise RuntimeError("CANCELLED_BY_USER")
        try:
            _out, err = proc.communicate(timeout=1)
            break
        except subprocess.TimeoutExpired:
            if time.time() > deadline:
                proc.kill()
                _out, err = proc.communicate()
                raise RuntimeError(f"ffmpeg timed out after {int(timeout_sec)}s")
            continue

    if proc.returncode != 0:
        tail = (err or "").strip()[-2000:]
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {tail or 'no stderr output'}")


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


_PLATFORM_DOMAINS = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "tiktok.com": "tiktok",
    "instagram.com": "instagram",
    "instagr.am": "instagram",
}


def detect_platform(url: str) -> str:
    """Platform from the URL's host name, so "evil.example/?youtube.com" stays unknown."""
    try:
        host = (urllib.parse.urlparse(url.strip()).hostname or "").lower()
    except ValueError:
        return "unknown"
    for domain, platform in _PLATFORM_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return platform
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
        event = job_cancel_events.get(job_id)
        if event is not None and event.is_set():
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
        "noplaylist": True,
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
        "noplaylist": True,
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
                "noplaylist": True,
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
        "noplaylist": True,
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


def extract_clip_segment(
    source_path: str,
    out_clip: str,
    start_sec: float,
    end_sec: float,
    ratio: str = "16:9",
    cancel_event: Optional[threading.Event] = None,
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
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_clip,
    ])
    _run_ffmpeg(cmd, timeout_sec=dur * 4 + 120, cancel_event=cancel_event)
    return out_clip


def format_video_target(input_path: str, ratio: str = "original", fps: str = "auto", cancel_event: Optional[threading.Event] = None) -> str:
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
        "-pix_fmt", "yuv420p",
        "-threads", "0",
        out_path
    ])

    _run_ffmpeg(cmd, timeout_sec=7200, cancel_event=cancel_event)
    return out_path


# Request models
class InfoRequest(BaseModel):
    url: str


class ProcessRequest(BaseModel):
    url: str
    action: Literal[
        "type_yt_ai_clip", "type_ig_ai_clip", "type_yt_video", "type_yt_short", "type_yt_mp3",
        "type_ig_reels", "ig_reels", "type_tt_video", "tt_video",
        "type_tt_mp3", "type_yt_clip", "ai_clip", "mp3", "manual_clip",
    ]
    num_clips: int = Field(5, ge=1, le=20)
    aspect_ratio: str = "9:16"
    use_face_detect: bool = False
    quality: str = "1080"
    fps: Optional[str] = "auto"
    start_time: str = "00:00"
    end_time: str = "00:30"
    segments: Optional[List[Dict[str, str]]] = Field(default=None, max_length=20)
    workspace_name: Optional[str] = "Workspace 01"

    @field_validator("aspect_ratio")
    @classmethod
    def _check_ratio(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if cleaned not in ("original", "16:9", "9:16", "3:4", "1:1"):
            raise ValueError("Unsupported aspect ratio")
        return cleaned

    @field_validator("quality")
    @classmethod
    def _check_quality(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        return cleaned if cleaned in ("1080", "720", "480", "360") else "1080"

    @field_validator("fps")
    @classmethod
    def _check_fps(cls, value: Optional[str]) -> str:
        cleaned = str(value or "auto").strip()
        return cleaned if cleaned in ("auto", "30", "60") else "auto"

    @field_validator("workspace_name")
    @classmethod
    def _check_workspace(cls, value: Optional[str]) -> str:
        cleaned = " ".join(str(value or "").split()).strip()
        return cleaned[:80] or "Workspace 01"


class RenameProjectRequest(BaseModel):
    new_name: str

    @field_validator("new_name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        cleaned = " ".join(str(value or "").split()).strip()
        if not cleaned:
            raise ValueError("Name cannot be empty")
        return cleaned[:80]


class OpenFileRequest(BaseModel):
    file_path: str


def _html_headers() -> Dict[str, str]:
    """Headers for the two HTML pages. The CSP allows the pinned CDNs the UI uses."""
    return {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "img-src 'self' data: blob: https:; "
            "media-src 'self' blob: https:; "
            "connect-src 'self' https:; "
            "frame-ancestors 'none'"
        ),
    }


def _asset_version() -> str:
    """Changes whenever a UI file changes, so browsers never pair new HTML with cached JS."""
    ui_dir = os.path.join(ASSETS_DIR, "ui")
    try:
        return str(int(max(os.path.getmtime(os.path.join(ui_dir, n)) for n in os.listdir(ui_dir))))
    except (OSError, ValueError):
        return "0"


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read().replace("{{ASSET_VERSION}}", _asset_version())
        return HTMLResponse(content=content, headers=_html_headers())
    return HTMLResponse("<h1>Templates not found.</h1>", status_code=404)


@app.get("/guide")
async def guide_page():
    # The guide lives in a tab of the main page; this keeps old links working.
    return RedirectResponse("/#guide")



@app.post("/api/info")
async def api_info(req: InfoRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    problem = external_url_problem(url)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

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
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    problem = external_url_problem(url)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    try:
        from .clipper.downloader import _extract_youtube_video_id
        vid = _extract_youtube_video_id(url)
        if not vid:
            return {"has_transcript": True, "provider": transcribe_provider_label()}

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
            "provider": "YouTube Subtitle Scraper" if has_t else transcribe_provider_label(),
            "note": "Official YouTube transcript is available" if has_t else "No official transcript is available; using AI speech-to-text"
        }
    except Exception:
        return {"has_transcript": True, "provider": transcribe_provider_label()}


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
        raise FileNotFoundError(f"Media file is missing: {file_path}")
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
        # Defence in depth: a crafted prefix must never escape the category folder.
        if os.path.dirname(os.path.abspath(vault_file_path)) != os.path.abspath(target_vault_dir):
            raise ValueError("Refusing to write outside the Media Vault category folder")
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
        raise


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
        # folder_path comes from meta.json, which may be stale or edited by hand.
        if not _path_is_inside(target_vault_dir, [storage_root_path]):
            raise ValueError("Workspace folder is outside the Media Vault")

        saved_files = []
        for item in files_to_save:
            src_path = item.get("file_path")
            if src_path and os.path.exists(src_path):
                fname = os.path.basename(src_path)
                dst_path = os.path.join(target_vault_dir, fname)
                if os.path.abspath(src_path) != os.path.abspath(dst_path):
                    # Never overwrite a different recording that happens to share a name
                    # (AI clips are always short_00.mp4 ...), and never let a second run
                    # leave the first run's metadata attached to new bytes.
                    if os.path.exists(dst_path) and os.path.getsize(dst_path) != os.path.getsize(src_path):
                        stem, suffix = os.path.splitext(fname)
                        fname = f"{stem}_{uuid.uuid4().hex[:6]}{suffix}"
                        dst_path = os.path.join(target_vault_dir, fname)
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
                    if isinstance(data, list):
                        records = [d for d in data if isinstance(d, dict)]
                        existing_record = next(
                            (r for r in records if isinstance(r.get("files"), list)),
                            records[0] if records else None,
                        )
                    elif isinstance(data, dict):
                        existing_record = data
            except Exception:
                existing_record = None

        if existing_record:
            combined_files = [f for f in existing_record.get("files", []) if isinstance(f, dict)]
            index_by_name = {
                f.get("filename"): idx for idx, f in enumerate(combined_files) if f.get("filename")
            }
            for sf in saved_files:
                idx = index_by_name.get(sf.get("filename"))
                if idx is None:
                    combined_files.append(sf)
                    index_by_name[sf.get("filename")] = len(combined_files) - 1
                else:
                    # Same file written again: refresh its metadata instead of keeping stale values.
                    combined_files[idx] = sf
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
        raise


def _worker_process(job_id: str, req: ProcessRequest):
    cancel_event = job_cancel_events.get(job_id)

    def _cancelled() -> bool:
        return bool(cancel_event and cancel_event.is_set()) or bool(jobs.get(job_id, {}).get("cancelled"))

    def _set_progress(value: float) -> None:
        """Progress never moves backwards (the old stage table went 50 -> 40 -> 35)."""
        if job_id not in jobs:
            return
        jobs[job_id]["progress"] = max(float(jobs[job_id].get("progress") or 0.0), float(value))

    if _cancelled():
        job_finished.add(job_id)
        return

    job_output_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_output_dir, exist_ok=True)

    url = req.url.strip()
    platform = detect_platform(url)
    action = req.action
    ws_name = req.workspace_name or "Workspace 01"
    if ws_name == ".." or "/" in ws_name or "\\" in ws_name:
        ws_name = "Workspace 01"

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
                if _cancelled():
                    raise RuntimeError("CANCELLED_BY_USER")
                jobs[job_id]["stage"] = stage
                jobs[job_id]["logs"].append(f"Stage: {stage}")
                if stage in ("downloading", "queued"):
                    _set_progress(20.0)
                elif stage == "checking_transcript":
                    _set_progress(30.0)
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "Checking YouTube captions..."
                elif stage == "transcript_found":
                    _set_progress(50.0)
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "YouTube transcript found"
                elif stage == "transcribing_groq":
                    _set_progress(40.0)
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = f"Transcribing audio with {transcribe_provider_label()}..."
                elif stage == "transcribing_local":
                    _set_progress(40.0)
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "Transcribing audio with local Faster-Whisper..."
                elif stage in ("transcribing", "extracting_audio", "uploading"):
                    _set_progress(35.0)
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "Extracting and transcribing audio..."
                elif stage in ("ranking_highlights", "detecting_highlights"):
                    _set_progress(65.0)
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "Analyzing viral potential and clip moments..."
                elif stage.startswith("rendering_"):
                    parts = stage.split("_")
                    if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                        done_c = int(parts[1])
                        tot_c = int(parts[2])
                        pct = 68.0 + (done_c / max(tot_c, 1)) * 27.0
                        _set_progress(round(pct, 1))
                        jobs[job_id]["stage_detail"] = f"Rendering clip {done_c}/{tot_c}"
                    jobs[job_id]["stage"] = "rendering"
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                elif stage in ("clipping", "rendering"):
                    _set_progress(70.0)
                    jobs[job_id]["download_speed"] = ""
                    jobs[job_id]["download_eta"] = ""
                    jobs[job_id]["stage_detail"] = "Rendering 9:16 clips (vertical crop)..."
                elif stage == "saving":
                    _set_progress(96.0)
                    jobs[job_id]["stage_detail"] = "Saving to Media Vault..."
                elif stage == "done":
                    _set_progress(100.0)
                    jobs[job_id]["stage_detail"] = "Complete"

            result = generate_shorts(
                youtube_url=url,
                num_clips=req.num_clips,
                aspect_ratio=req.aspect_ratio,
                download_format=req.quality,
                language=None,
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

            if not _cancelled():
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
                    file_path = format_video_target(file_path, ratio=req.aspect_ratio, fps=req.fps or "auto", cancel_event=cancel_event)
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
                jobs[job_id]["logs"].append(f"Saved to Media Vault ({ws_name}).")
            except Exception as v_err:
                print(f"[Vault Error] {v_err}", flush=True)
                jobs[job_id]["logs"].append(f"Media Vault warning: {v_err}")

            if not _cancelled():
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
                jobs[job_id]["logs"].append(f"Saved to Media Vault ({ws_name}).")
            except Exception as v_err:
                print(f"[Vault Error] {v_err}", flush=True)
                jobs[job_id]["logs"].append(f"Media Vault warning: {v_err}")

            if not _cancelled():
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
                jobs[job_id]["logs"].append(f"Saved to Media Vault ({ws_name}).")
            except Exception as v_err:
                print(f"[Vault Error] {v_err}", flush=True)
                jobs[job_id]["logs"].append(f"Media Vault warning: {v_err}")

            if not _cancelled():
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
                jobs[job_id]["logs"].append(f"Saved to Media Vault ({ws_name}).")
            except Exception as v_err:
                print(f"[Vault Error] {v_err}", flush=True)
                jobs[job_id]["logs"].append(f"Media Vault warning: {v_err}")

            if not _cancelled():
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
                "noplaylist": True,
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
                    cancel_event=cancel_event,
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

            # Register to Media Vault. Both single and multi trims become a workspace,
            # otherwise "Open Workspace" had no project to open for a one-segment trim.
            try:
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
                jobs[job_id]["logs"].append(
                    f"Saved to Trim Workspace: {ws_name} ({len(files_to_save)} clip(s))."
                )
            except Exception as v_err:
                print(f"[Vault Trimmer Error] {v_err}", flush=True)
                jobs[job_id]["logs"].append(f"Media Vault warning: {v_err}")

            if not _cancelled():
                jobs[job_id]["status"] = "completed"
                jobs[job_id]["stage"] = "done"
                jobs[job_id]["progress"] = 100.0

        else:
            raise ValueError(f"Unknown action: {action}")

    except Exception as e:
        if str(e) == "CANCELLED_BY_USER" or _cancelled():
            if job_id in jobs:
                jobs[job_id]["status"] = "cancelled"
                jobs[job_id]["stage"] = "cancelled"
                jobs[job_id]["logs"].append("Job cancelled by user.")
            return
        import traceback
        traceback.print_exc()
        if job_id in jobs:
            message = friendly_error_message(e)
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = message
            jobs[job_id]["error_detail"] = str(e)
            jobs[job_id]["logs"].append(f"Error: {message}")
    finally:
        # The worker owns cleanup: deleting the folder from the cancel endpoint
        # pulled the rug out from under yt-dlp/ffmpeg still writing into it.
        job_finished.add(job_id)
        if _cancelled():
            _cleanup_job_output(job_id)
        else:
            try:
                _save_job(job_id)
            except OSError as e:
                logger.warning(f"Could not save job {job_id}: {e}")


@app.post("/api/process")
async def api_process(req: ProcessRequest, background_tasks: BackgroundTasks):
    problem = external_url_problem(req.url)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    # Validate trim input before accepting the job: a bad timestamp used to become
    # a clip rendered at the wrong offset instead of a 400.
    if req.action in ("type_yt_clip", "manual_clip"):
        segments = req.segments or [{"start_time": req.start_time, "end_time": req.end_time}]
        for seg in segments:
            try:
                start_s = parse_timestamp(seg.get("start_time") or "00:00")
                end_s = parse_timestamp(seg.get("end_time") or "00:30")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            if end_s <= start_s:
                raise HTTPException(status_code=400, detail="End time must be after start time")

    _prune_old_jobs(50)
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id,
        "url": req.url.strip(),
        "action": req.action,
        "workspace_name": req.workspace_name or "Workspace 01",
        "status": "queued",
        "stage": "queued",
        "stage_detail": "",
        "progress": 0.0,
        "download_speed": "",
        "download_eta": "",
        "download_frags": "",
        "cancelled": False,
        "logs": ["Job added to queue..."],
        "results": [],
        "project_id": None,
        "error": None,
    }
    job_cancel_events[job_id] = threading.Event()
    job_finished.discard(job_id)
    job_requests[job_id] = req.model_dump()

    background_tasks.add_task(_worker_process, job_id, req)
    return {"job_id": job_id, "status": "queued"}


def _retryable(job_id: str) -> bool:
    job = jobs.get(job_id) or {}
    return job.get("status") == "failed" and job_id in job_finished and job_id in job_requests


@app.post("/api/retry/{job_id}")
async def api_retry(job_id: str, background_tasks: BackgroundTasks):
    """Run a failed job again in its own folder, so finished or partial downloads are reused."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    if not _retryable(job_id):
        raise HTTPException(status_code=409, detail="Only a failed job can be retried")
    try:
        req = ProcessRequest(**job_requests[job_id])
    except Exception:
        raise HTTPException(status_code=409, detail="This job's saved settings are no longer valid")
    problem = external_url_problem(req.url)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    jobs[job_id].update(
        status="queued", stage="queued", stage_detail="", progress=0.0,
        cancelled=False, results=[], error=None, error_detail=None,
    )
    jobs[job_id]["logs"].append("Retrying...")
    job_cancel_events[job_id] = threading.Event()
    job_finished.discard(job_id)
    background_tasks.add_task(_worker_process, job_id, req)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/status/{job_id}")
async def api_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    # The worker thread mutates this dict continuously; copy before serializing.
    return {**copy.deepcopy(job), "retryable": _retryable(job_id)}


@app.get("/api/download-file/{job_id}/{filename}")
async def api_download_file(job_id: str, filename: str):
    file_path = _safe_output_file(job_id, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # FileResponse already builds an RFC 5987 filename; the manual header we used to
    # add crashed with UnicodeEncodeError for any emoji/CJK title.
    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@app.get("/api/download-zip/{job_id}")
async def api_download_zip(job_id: str, background_tasks: BackgroundTasks):
    if job_id not in jobs or jobs[job_id].get("status") != "completed":
        raise HTTPException(status_code=400, detail="Job is not complete or was not found")

    _safe_output_job_dir(job_id)
    zip_filename = f"media_{job_id}.zip"
    fd, zip_path = tempfile.mkstemp(prefix=f"luna_{job_id}_", suffix=".zip")
    os.close(fd)

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

    # Temporary file, removed after the response is sent instead of piling up in output/.
    background_tasks.add_task(os.remove, zip_path)
    return FileResponse(zip_path, filename=zip_filename, media_type="application/zip")


@app.post("/api/cancel/{job_id}")
async def api_cancel(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.get("status") in ("completed", "failed", "cancelled"):
        # Cancelling a finished job used to delete its output folder, so every
        # download link for that job started returning 404.
        return {"status": job.get("status"), "job_id": job_id, "detail": "Job already finished"}

    event = job_cancel_events.setdefault(job_id, threading.Event())
    event.set()
    job["cancelled"] = True
    job["status"] = "cancelled"
    job["stage"] = "cancelled"
    job["logs"].append("Cancellation requested; stopping the worker...")

    # The worker owns the folder cleanup (it may still be writing while ffmpeg/yt-dlp
    # are alive; deleting underneath them produced WinError 32 and orphaned partials).
    return {"status": "cancelled", "job_id": job_id}


# Media vault routes
@app.get("/api/vault")
async def api_get_vault():
    # Full-tree walks are blocking; keep them off the event loop.
    items = await asyncio.to_thread(list_vault_items)
    stats = await asyncio.to_thread(get_storage_stats)
    return {"items": items, "stats": stats}


@app.get("/api/vault/projects")
async def api_get_vault_projects():
    projects = await asyncio.to_thread(list_vault_projects)
    stats = await asyncio.to_thread(get_storage_stats)
    next_index = await asyncio.to_thread(get_next_workspace_index)
    return {
        "projects": projects,
        "stats": stats,
        "next_workspace_index": next_index,
    }


@app.patch("/api/vault/project/{project_id}/rename")
async def api_rename_vault_project(project_id: str, req: RenameProjectRequest):
    if await asyncio.to_thread(workspace_name_taken, req.new_name, project_id):
        raise HTTPException(status_code=409, detail="Another workspace already uses that name")
    success = await asyncio.to_thread(rename_vault_project, project_id, req.new_name)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "renamed", "project_id": project_id, "new_name": req.new_name}


@app.delete("/api/vault/project/{project_id}")
async def api_delete_vault_project(project_id: str):
    result = await asyncio.to_thread(delete_vault_project, project_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Project not found")
    if result == "locked":
        raise HTTPException(status_code=409, detail="Some files are open elsewhere. Close them and try again.")
    return {"status": "deleted", "project_id": project_id}


@app.delete("/api/vault/{item_id}")
async def api_delete_vault(item_id: str):
    result = await asyncio.to_thread(delete_vault_item, item_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Item not found in Media Vault")
    if result == "locked":
        raise HTTPException(status_code=409, detail="The file is open elsewhere. Close it and try again.")
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


def _browse_folder_dialog() -> str:
    """Blocking native folder picker; runs in a worker thread, never on the event loop."""
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

    return selected_path


@app.post("/api/settings/browse-folder")
async def api_browse_folder():
    selected_path = await asyncio.to_thread(_browse_folder_dialog)
    return {"status": "success" if selected_path else "cancelled", "path": selected_path}


def _system_status_sync() -> Dict[str, Any]:
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


@app.post("/api/settings/check-system")
async def api_check_system():
    return await asyncio.to_thread(_system_status_sync)


def _mask_key(value: str) -> str:
    """Return a display-only hint instead of the secret itself."""
    key = (value or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}...{key[-4:]}"


# Settings routes
class SettingsUpdateRequest(BaseModel):
    llm_provider: Optional[str] = None
    transcribe_provider: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    storage_dir: Optional[str] = None
    migrate_files: Optional[bool] = False

    @field_validator("openai_api_key", "gemini_api_key", "groq_api_key")
    @classmethod
    def _check_secret(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if "\n" in cleaned or "\r" in cleaned:
            raise ValueError("API keys cannot contain line breaks")
        if len(cleaned) > 512:
            raise ValueError("API key is too long")
        return cleaned

    @field_validator("openai_model", "storage_dir")
    @classmethod
    def _check_single_line(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if "\n" in value or "\r" in value:
            raise ValueError("This value cannot contain line breaks")
        return value.strip()


class OpenAIModelsRequest(BaseModel):
    api_key: str = ""
    base_url: Optional[str] = None


class TestKeyRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


@app.get("/api/settings")
async def api_get_settings():
    cookie_path = os.path.join(BASE_DIR, "cookies.txt")
    has_cookies = os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0
    cookie_size = f"{os.path.getsize(cookie_path) / 1024:.1f} KB" if has_cookies else "0 KB"

    try:
        import cv2  # noqa: F401  (imported only to check that OpenCV is installed)
        has_opencv = True
    except Exception:
        has_opencv = False

    has_ffmpeg = bool(shutil.which("ffmpeg") or os.path.exists(r"C:\ffmpeg\bin\ffmpeg.exe"))
    ytdlp_ver = str(getattr(yt_dlp.version, "__version__", "v2025.02.19"))
    curr_storage = get_storage_root()

    openai_key = os.getenv("OPENAI_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")

    return {
        "llm_provider": os.getenv("LLM_PROVIDER", "").strip().lower(),
        "transcribe_provider": transcribe_provider(),
        # Secrets are never echoed back; only a hint plus a configured flag.
        "openai_api_key": _mask_key(openai_key),
        "openai_api_key_set": bool(openai_key.strip()),
        "has_openai_api_key": bool(openai_key.strip()),
        "openai_base_url": openai_base_url(),
        "openai_model": openai_model(),
        "gemini_api_key": _mask_key(gemini_key),
        "has_gemini_api_key": bool(gemini_key.strip()),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        "groq_api_key": _mask_key(groq_key),
        "has_groq_api_key": bool(groq_key.strip()),
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
    # Blank means automatic, see llm_provider() in the clipper config.
    if req.llm_provider is not None:
        value = req.llm_provider.strip().lower()
        if value not in ("", "openai", "gemini"):
            raise HTTPException(status_code=400, detail="Unknown clip analysis provider")
        updates["LLM_PROVIDER"] = value
    if req.transcribe_provider is not None:
        value = req.transcribe_provider.strip().lower()
        if value not in ("groq", "gemini", "whisper"):
            raise HTTPException(status_code=400, detail="Unknown transcription provider")
        updates["LOCAL_TRANSCRIBE_PROVIDER"] = value
    if req.openai_base_url is not None and req.openai_base_url.strip():
        if not req.openai_base_url.strip().startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Base URL must start with http:// or https://")
    for env_key, value in (
        ("OPENAI_BASE_URL", req.openai_base_url),
        ("OPENAI_MODEL", req.openai_model),
    ):
        if value is not None:
            updates[env_key] = value.strip()
    # A blank secret means "keep the stored one", and so does re-submitting the masked
    # hint: the UI only ever receives a mask, so echoing it back must not destroy a key.
    for env_key, value in (
        ("OPENAI_API_KEY", req.openai_api_key),
        ("GEMINI_API_KEY", req.gemini_api_key),
        ("GROQ_API_KEY", req.groq_api_key),
    ):
        if value and value.strip() != _mask_key(os.getenv(env_key, "")):
            updates[env_key] = value.strip()

    migrated_info = None
    if req.storage_dir is not None and req.storage_dir.strip():
        norm_dir = os.path.abspath(req.storage_dir.strip())
        if not await asyncio.to_thread(is_writable, norm_dir):
            raise HTTPException(status_code=400, detail="Storage directory is inaccessible or not writable.")

        old_dir = get_storage_root()
        if req.migrate_files and os.path.abspath(old_dir) != os.path.abspath(norm_dir):
            from . import storage_manager
            try:
                # Copying gigabytes on the event loop froze every other request.
                migrated_info = await asyncio.to_thread(storage_manager.migrate_storage, old_dir, norm_dir)
            except Exception as e:
                logger.error(f"Error migrating storage: {e}")
                raise HTTPException(status_code=500, detail=f"Could not move files: {e}")

        updates["MEDIA_STORAGE_DIR"] = norm_dir
        os.environ["MEDIA_STORAGE_DIR"] = norm_dir
        invalidate_storage_root_cache()

    try:
        _update_env_file(updates)
    except OSError as e:
        # Read-only mount or wrong ownership: report it instead of a bare traceback.
        raise HTTPException(status_code=500, detail=f"Could not write .env: {e}")
    return {
        "status": "saved",
        "storage_dir": get_storage_root(),
        "migrated": migrated_info,
        "stats": await asyncio.to_thread(get_storage_stats),
    }


_ENV_LOCK = threading.Lock()


def _update_env_file(updates: dict):
    """Serialize .env read-modify-write; two Settings saves used to clobber each other."""
    with _ENV_LOCK:
        _update_env_file_locked(updates)


def _update_env_file_locked(updates: dict):
    for key, value in updates.items():
        text = str(value)
        if "\n" in text or "\r" in text:
            # An embedded newline would append arbitrary KEY=value lines to .env.
            raise ValueError(f"Value for {key} cannot contain line breaks")

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

    _write_text_compat(env_path, "".join(new_lines))


def _try_atomic_write(path: str, text: str) -> bool:
    """Stage the text next to the target and rename it. False when the filesystem says no."""
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        return True
    except OSError:
        return False
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _write_text_compat(path: str, text: str) -> None:
    """Write text, atomically when possible and through the file when not.

    Two Docker cases break the tidy "temp file + rename" pattern:
      * .env / cookies.txt are single-file bind mounts, where rename fails with EBUSY;
      * the mounted app directory may be owned by a different uid than the container
        user (compose overrides user with LUNA_UID), so creating a temp file there is
        denied even though the file itself is writable.
    Fall back to truncating the file in place, which only needs write access to it.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    if os.access(directory, os.W_OK) and _try_atomic_write(path, text):
        return

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


@app.post("/api/settings/openai-models")
async def api_openai_models(req: OpenAIModelsRequest):
    key = req.api_key.strip()
    base_url = (req.base_url or "").strip().rstrip("/") or DEFAULT_OPENAI_BASE_URL
    # Without a typed key, fall back to the saved one, but only for the saved base URL,
    # so a request can never send the saved key to an address it chose.
    if not key and base_url == openai_base_url().rstrip("/"):
        key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="API key and an http(s) base URL are required")
    try:
        resp = await asyncio.to_thread(
            requests.get, f"{base_url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=8
        )
        resp.raise_for_status()
        ids = [m["id"] for m in resp.json()["data"]]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not list models: {type(e).__name__}")
    # Clip analysis needs a chat model, and these name patterns can never be one.
    return {"models": sorted(i for i in ids if not re.search(r"embedding|whisper|tts|transcribe", i, re.I))}


@app.post("/api/settings/test-key")
async def api_test_key(req: TestKeyRequest):
    provider = req.provider.lower()
    env_key = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}.get(provider)
    if not env_key:
        return {"valid": False, "message": "Unknown provider"}
    # An empty request means test the configured key without returning it to the browser.
    key = (req.api_key or "").strip() or os.getenv(env_key, "").strip()
    if not key:
        return {"valid": False, "message": "No API key is configured"}

    if provider == "openai":
        base_url = (req.base_url or "").strip().rstrip("/") or DEFAULT_OPENAI_BASE_URL
        if not base_url.startswith(("http://", "https://")):
            return {"valid": False, "message": "Base URL must start with http(s)://"}
        # Same rule as the model list: the saved key only goes to the saved base URL.
        if not (req.api_key or "").strip() and base_url != openai_base_url().rstrip("/"):
            return {"valid": False, "message": "Enter the key to test it against this base URL"}
        try:
            resp = await asyncio.to_thread(
                requests.get,
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=8,
            )
            if resp.status_code == 200:
                return {"valid": True, "message": "200 OK"}
            return {"valid": False, "message": f"{resp.status_code} Error"}
        except Exception as e:
            return {"valid": False, "message": str(e)[:40]}

    if provider == "gemini":
        try:
            # Header auth: a key in the query string ends up in proxy/access logs.
            resp = await asyncio.to_thread(
                requests.get,
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": key},
                timeout=8,
            )
            if resp.status_code == 200:
                return {"valid": True, "message": "200 OK"}
            else:
                return {"valid": False, "message": f"{resp.status_code} Error"}
        except Exception as e:
            return {"valid": False, "message": str(e)[:40]}

    elif provider == "groq":
        try:
            resp = await asyncio.to_thread(
                requests.get,
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=8,
            )
            if resp.status_code == 200:
                return {"valid": True, "message": "200 OK"}
            else:
                return {"valid": False, "message": f"{resp.status_code} Error"}
        except Exception as e:
            return {"valid": False, "message": str(e)[:40]}

    return {"valid": False, "message": "Unknown provider"}


class CookieUploadRequest(BaseModel):
    filename: Optional[str] = "cookies.txt"
    content: str

    @field_validator("content")
    @classmethod
    def _check_content(cls, value: str) -> str:
        if len(value.encode("utf-8", errors="ignore")) > 5 * 1024 * 1024:
            raise ValueError("Cookie file is too large (max 5 MB)")
        if "\x00" in value:
            raise ValueError("Cookie file contains binary data")
        return value


@app.post("/api/settings/upload-cookies")
async def api_upload_cookies(req: CookieUploadRequest):
    cookie_path = os.path.join(BASE_DIR, "cookies.txt")
    try:
        _write_text_compat(cookie_path, req.content)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write cookies.txt: {e}")
    size_kb = f"{len(req.content.encode('utf-8')) / 1024:.1f} KB"
    return {"status": "uploaded", "filename": req.filename or "cookies.txt", "size": size_kb}


# Old job folders are temporary: the vault keeps its own copy of every saved file.
try:
    cleanup_expired_jobs(int(os.getenv("LUNA_JOB_RETENTION_DAYS", "30")))
except Exception as _cleanup_err:  # pragma: no cover - best effort at startup
    logger.warning(f"Could not clean old job folders: {_cleanup_err}")

