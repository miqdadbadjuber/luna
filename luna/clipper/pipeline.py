# SPDX-License-Identifier: MIT
# This file is part of Luna's clip pipeline. See luna/clipper/LICENSE and
# THIRD_PARTY_NOTICES.md for the upstream notice.

"""End-to-end orchestrator: yt-dlp, transcription, LLM ranking, then ffmpeg/opencv rendering."""
from typing import Callable, Dict, List, Optional

from .clipper import crop_highlights_local
from .downloader import download_youtube_local, get_last_download_info, reset_last_download_info
from .highlights import get_highlights
from .llm import call_llm
from .transcriber import transcribe_local


def generate_shorts(
    youtube_url: str,
    num_clips: int = 3,
    aspect_ratio: str = "9:16",
    download_format: str = "720",
    language: Optional[str] = None,
    use_face_detect: bool = True,
    on_status: Optional[Callable[[str], None]] = None,
    out_dir: Optional[str] = None,
    progress_hook: Optional[Callable] = None,
) -> Dict:
    """Run the full pipeline and return a structured result."""
    # downloader keeps the metadata as a process global: clear it before the
    # download so a reused local file or cached download cannot inherit the
    # previous job's title
    reset_last_download_info()
    source_path = download_youtube_local(
        youtube_url, fmt=download_format, out_dir=out_dir, progress_hook=progress_hook
    )

    transcript = transcribe_local(source_path, video_url=youtube_url, language=language, on_status=on_status)
    if not transcript["segments"]:
        raise RuntimeError(
            "Whisper produced no segments. The video may have no detectable speech."
        )

    if on_status:
        on_status("ranking_highlights")
    highlights_result = get_highlights(transcript, num_clips=num_clips, llm_fn=call_llm)
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    print(f"[pipeline] cropping {len(top)} of {len(all_highlights)} candidates", flush=True)

    if on_status:
        on_status("rendering")

    def _on_clip_progress(done: int, total: int):
        if on_status:
            on_status(f"rendering_{done}_{total}")

    shorts = crop_highlights_local(
        source_path, top, aspect_ratio=aspect_ratio, out_dir=out_dir, use_face_detect=use_face_detect, on_progress=_on_clip_progress,
        transcript_segments=transcript["segments"],
    )

    # A job with no clips must fail visibly instead of reporting success with an empty result.
    if not any(s.get("clip_url") for s in shorts):
        errors = [s["error"] for s in shorts if s.get("error")]
        raise RuntimeError(f"All clips failed to render: {errors[0] if errors else 'unknown error'}")

    info = get_last_download_info()
    return {
        "source_video_url": source_path,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
        "title": info.get("title", ""),
        "channel": info.get("channel") or info.get("uploader", ""),
        "transcribe_provider": transcript.get("provider", "Groq Cloud Whisper"),
    }
