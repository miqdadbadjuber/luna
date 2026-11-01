"""End-to-end orchestrator.

Two modes:
  * mode="api"   (default) — MuAPI does download / transcribe / LLM / autocrop.
                              Fast, no local deps, pay-per-call.
  * mode="local"            — yt-dlp + faster-whisper + OpenAI or Gemini + ffmpeg/opencv.
                              Self-hosted, LLM_PROVIDER selects OpenAI or Gemini.
"""
from typing import Callable, Dict, List, Optional

from .clipper import crop_highlights
from .config import LOCAL_TRANSCRIBE_PROVIDER
from .downloader import download_youtube
from .highlights import call_muapi_llm, get_highlights
from .transcriber import transcribe


def _run_local(
    youtube_url: str,
    num_clips: int,
    aspect_ratio: str,
    download_format: str,
    language: Optional[str],
    use_face_detect: bool = True,
    on_status: Optional[Callable[[str], None]] = None,
    out_dir: Optional[str] = None,
    progress_hook: Optional[Callable] = None,
) -> Dict:
    from .local.clipper import crop_highlights_local
    from .local.downloader import download_youtube_local, get_last_download_info
    from .local.llm import call_local_llm
    from .local.transcriber import transcribe_local

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
    highlights_result = get_highlights(transcript, num_clips=num_clips, llm_fn=call_local_llm)
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    print(f"[pipeline/local] cropping {len(top)} of {len(all_highlights)} candidates", flush=True)

    if on_status:
        on_status("rendering")

    def _on_clip_progress(done: int, total: int):
        if on_status:
            on_status(f"rendering_{done}_{total}")

    shorts = crop_highlights_local(
        source_path, top, aspect_ratio=aspect_ratio, out_dir=out_dir, use_face_detect=use_face_detect, on_progress=_on_clip_progress
    )

    info = get_last_download_info()
    return {
        "mode": "local",
        "source_video_url": source_path,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
        "title": info.get("title", ""),
        "channel": info.get("channel") or info.get("uploader", ""),
        "transcribe_provider": transcript.get("provider", "Groq Cloud Whisper"),
    }


def _run_api(
    youtube_url: str,
    num_clips: int,
    aspect_ratio: str,
    download_format: str,
    language: Optional[str],
) -> Dict:
    source_url = download_youtube(youtube_url, fmt=download_format)

    transcript = transcribe(source_url, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Whisper produced no segments. The video may have no detectable speech."
        )

    highlights_result = get_highlights(transcript, num_clips=num_clips, llm_fn=call_muapi_llm)
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    print(f"[pipeline] cropping {len(top)} of {len(all_highlights)} candidates", flush=True)

    shorts = crop_highlights(source_url, top, aspect_ratio=aspect_ratio)

    return {
        "mode": "api",
        "source_video_url": source_url,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
    }


def generate_shorts(
    youtube_url: str,
    num_clips: int = 3,
    aspect_ratio: str = "9:16",
    download_format: str = "720",
    language: Optional[str] = None,
    mode: str = "api",
    use_face_detect: bool = True,
    on_status: Optional[Callable[[str], None]] = None,
    out_dir: Optional[str] = None,
    progress_hook: Optional[Callable] = None,
) -> Dict:
    """Run the full pipeline and return a structured result."""
    mode = (mode or "api").lower()
    if mode == "local":
        return _run_local(
            youtube_url, num_clips, aspect_ratio, download_format, language,
            use_face_detect=use_face_detect, on_status=on_status, out_dir=out_dir,
            progress_hook=progress_hook,
        )
    if mode == "api":
        return _run_api(youtube_url, num_clips, aspect_ratio, download_format, language)
    raise ValueError(f"Unknown mode: {mode!r}. Use 'api' or 'local'.")