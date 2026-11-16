# SPDX-License-Identifier: MIT
# This file is part of Luna's clip pipeline. See luna/clipper/LICENSE and
# THIRD_PARTY_NOTICES.md for the upstream notice.

"""Local YouTube download via yt-dlp.

Returns a local mp4 path so the rest of the local pipeline can read it
directly off disk.
"""
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from typing import Callable, Dict, Optional, Tuple

from .config import ROOT_DIR, local_output_dir
from .fast_http import create_youtube_dl


def _import_ytdlp():
    try:
        import yt_dlp  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e
    return yt_dlp


# Prefer H.264 at the chosen height. Unsorted, yt-dlp picks AV1: on an 80-minute video that
# was 290 MB against 132 MB, and face-tracked renders from it took up to 21% longer.
YOUTUBE_FORMAT_SORT = ["res", "vcodec:h264"]

# Single source of truth for yt-dlp network tuning across all downloaders:
# 4 concurrent fragments beats 12 under congested links, and dropping forced
# http_chunk_size / 64 KiB buffersize avoids HttpFD stalls when falling back
# from FastHttpFD.
YTDLP_DOWNLOAD_TUNING = {
    "socket_timeout": 15,
    "retries": 5,
    "fragment_retries": 5,
    "concurrent_fragment_downloads": 4,
}


def _format_for(fmt: str) -> str:
    """Map our '720' / '1080' shorthand to a fast yt-dlp format selector."""
    try:
        height = int(fmt)
    except ValueError:
        height = 1080
    return (
        f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
    )


def _extract_youtube_video_id(source: str) -> Optional[str]:
    """Best-effort extraction of a YouTube video id from a URL."""
    parsed = urlparse(source)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    if host in ("youtu.be", "www.youtu.be"):
        video_id = parsed.path.lstrip("/").split("/", 1)[0]
        return video_id or None

    if "youtube.com" in host:
        if parsed.path.startswith("/watch"):
            qs = parse_qs(parsed.query)
            video_id = qs.get("v", [""])[0]
            return video_id or None
        match = re.search(r"/(?:shorts|embed|live)/([^/?#&]+)", parsed.path)
        if match:
            return match.group(1)

    return None


def _resolve_local_path(source: str) -> Optional[str]:
    """Return a local filesystem path if the input already points at one."""
    parsed = urlparse(source)
    if parsed.scheme == "file":
        raw_path = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            raw_path = f"//{parsed.netloc}{raw_path}"
        candidate = Path(raw_path).expanduser()
        if candidate.exists() and candidate.is_file():
            return str(candidate.resolve())
        raise RuntimeError(f"Local file URL does not exist: {source}")

    if parsed.scheme in ("http", "https"):
        return None

    candidate = Path(source).expanduser()
    if candidate.exists() and candidate.is_file():
        return str(candidate.resolve())

    if any(sep in source for sep in (os.sep, "/")) or source.startswith("~") or source.startswith("."):
        raise RuntimeError(f"Local file path does not exist: {source}")

    return None


def _existing_download(out_dir: str, video_id: str, fmt: str) -> Optional[str]:
    """Return a cached download for this id at the requested height or higher.

    The filename carries the height (``source_<id>_<height>p.ext``), so a
    cached 1080p file must not be handed to a job that asked for 480p.
    """
    stem = f"source_{video_id}"
    for ext in (".mp4", ".mkv", ".webm"):
        exact = os.path.join(out_dir, f"{stem}_{fmt}p{ext}")
        if os.path.exists(exact):
            return exact

    try:
        requested = int(fmt)
    except (TypeError, ValueError):
        requested = 1080

    pattern = re.compile(rf"^{re.escape(stem)}_(\d+)p\.(?:mp4|mkv|webm)$", re.IGNORECASE)
    best: Optional[Tuple[int, str]] = None
    try:
        names = os.listdir(out_dir)
    except OSError:
        return None
    for name in names:
        match = pattern.match(name)
        if not match:
            continue
        height = int(match.group(1))
        # any height at or above the request is safe to reuse; prefer the closest one
        if height >= requested and (best is None or height < best[0]):
            best = (height, os.path.join(out_dir, name))
    return best[1] if best else None


_LAST_DOWNLOAD_INFO: Dict = {}


def reset_last_download_info() -> None:
    """Forget the previous job's metadata.

    Job dirs and the output folder are reused between runs, so the global would
    otherwise leak the previous video's title into a local-file job.
    """
    global _LAST_DOWNLOAD_INFO
    _LAST_DOWNLOAD_INFO = {}


def get_last_download_info() -> Dict:
    """Metadata for the most recent successful remote download of this job.

    Always empty right after reset_last_download_info(); a job that reuses a
    cached file or a local path leaves it empty because no fresh info exists.
    """
    global _LAST_DOWNLOAD_INFO
    return dict(_LAST_DOWNLOAD_INFO)


def download_youtube_local(
    video_url: str,
    fmt: str = "1080",
    out_dir: Optional[str] = None,
    progress_hook: Optional[Callable] = None,
) -> str:
    """Download a remote URL or return a local file path unchanged.

    Metadata is exposed through get_last_download_info() and is reset at the
    start of every call, including the local-file early return, so it always
    belongs to this job and never to the one before it.
    """
    reset_last_download_info()
    local_path = _resolve_local_path(video_url)
    if local_path:
        print(f"[download/local] using local file: {local_path}", flush=True)
        return local_path

    yt_dlp = _import_ytdlp()
    out_dir = out_dir or local_output_dir()
    if "=" in str(out_dir) or not str(out_dir).strip():
        out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)

    video_id = _extract_youtube_video_id(video_url)
    if video_id:
        cached = _existing_download(out_dir, video_id, fmt)
        if cached:
            print(f"[download/local] reusing cached download: {cached}", flush=True)
            return cached

    print(f"[download/local] {video_url} @ {fmt}p -> {out_dir}/", flush=True)
    cookie_file = os.path.join(ROOT_DIR, "cookies.txt")
    ydl_opts = {
        "format": _format_for(fmt),
        "format_sort": YOUTUBE_FORMAT_SORT,
        "outtmpl": os.path.join(out_dir, f"source_%(id)s_{fmt}p.%(ext)s"),
        "merge_output_format": "mp4",
        # Warnings stay on: they are the only sign that the JS challenge failed and YouTube throttled the download.
        "quiet": True,
        "noprogress": False,
        "noplaylist": True,
        "playlist_items": "1",
        **YTDLP_DOWNLOAD_TUNING,
    }
    if os.path.exists(cookie_file) and os.path.getsize(cookie_file) > 0:
        ydl_opts["cookiefile"] = cookie_file
    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    with create_youtube_dl(ydl_opts, ytdlp_mod=yt_dlp) as ydl:
        info = ydl.extract_info(video_url, download=True)
        # noplaylist should prevent this, but a bare playlist link can still slip through
        if info.get("_type") == "playlist":
            entries = [entry for entry in (info.get("entries") or []) if entry]
            if not entries:
                raise RuntimeError("Playlist URLs are not supported. Paste a single video link.")
            info = entries[0]
        global _LAST_DOWNLOAD_INFO
        _LAST_DOWNLOAD_INFO = {
            "title": info.get("title") or "",
            "channel": info.get("uploader") or info.get("channel") or info.get("creator") or "",
            "uploader": info.get("uploader") or "",
            "duration": info.get("duration") or 0,
        }
        # prepare_filename can disagree with where yt-dlp actually wrote the
        # merged file; trust requested_downloads when it points at a real file.
        requested = info.get("requested_downloads") or []
        path = ""
        if requested and isinstance(requested[0], dict):
            path = str(requested[0].get("filepath") or "")
        if not path or not os.path.exists(path):
            path = ydl.prepare_filename(info)
        # merge_output_format may rename the extension after merge
        if not os.path.exists(path):
            stem, _ = os.path.splitext(path)
            for ext in (".mp4", ".mkv", ".webm"):
                if os.path.exists(stem + ext):
                    path = stem + ext
                    break

    print(f"[download/local] ready: {path}", flush=True)
    return path
