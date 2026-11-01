"""Local transcription via faster-whisper.

Reads a local media file and returns the same shape the highlight generator
expects: {duration, segments[start, end, text]}.
"""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, Optional

from ..config import (
    GEMINI_MODEL,
    LOCAL_OUTPUT_DIR,
    LOCAL_TRANSCRIBE_PROVIDER,
    LOCAL_WHISPER_DEVICE,
    LOCAL_WHISPER_MODEL,
    require_gemini_key,
)


def _transcript_cache_path(media_path: str) -> Path:
    """Return the .srt cache path for a media file."""
    raw_dir = str(LOCAL_OUTPUT_DIR)
    if "=" in raw_dir or not raw_dir.strip():
        raw_dir = "output"
    cache_dir = Path(raw_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / (Path(media_path).stem + ".srt")


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt_timestamp(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value!r}")
    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + (millis / 1000.0)


def _write_srt_cache(media_path: str, transcript: Dict) -> Path:
    cache_path = _transcript_cache_path(media_path)
    lines = []
    for idx, segment in enumerate(transcript.get("segments", []), start=1):
        start = _format_srt_timestamp(float(segment["start"]))
        end = _format_srt_timestamp(float(segment["end"]))
        text = str(segment.get("text", "")).strip().replace("\r", "").replace("\n", " ")
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    cache_path.write_text("\n".join(lines), encoding="utf-8")
    return cache_path


def _load_srt_cache(cache_path: Path) -> Dict:
    content = cache_path.read_text(encoding="utf-8-sig").strip()
    if not content:
        return {"duration": 0.0, "segments": []}

    segments = []
    for block in re.split(r"\n\s*\n", content):
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[0].split("-->", 1)]
        text = "\n".join(lines[1:]).strip()
        segments.append(
            {
                "start": _parse_srt_timestamp(start_raw),
                "end": _parse_srt_timestamp(end_raw),
                "text": text,
            }
        )

    duration = segments[-1]["end"] if segments else 0.0
    return {"duration": duration, "segments": segments}


def _resolve_device() -> str:
    if LOCAL_WHISPER_DEVICE != "auto":
        return LOCAL_WHISPER_DEVICE
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            # Test that CUDA actually works (catches missing cuBLAS/cuDNN libs)
            torch.zeros(1, device="cuda")
            return "cuda"
    except (ImportError, OSError, RuntimeError):
        pass
    return "cpu"


def _parse_vtt_content(content: str) -> Dict:
    """Parse WebVTT subtitle text into standard duration + segments format."""
    segments = []
    pattern = re.compile(
        r"((?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})\s*-->\s*((?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})[^\n]*\n([\s\S]*?)(?=\n\s*(?:(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3}|$))"
    )

    def to_sec(ts: str) -> float:
        ts = ts.replace(",", ".")
        parts = ts.split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        return float(parts[0]) * 60 + float(parts[1])

    for match in pattern.finditer(content):
        s_str, e_str, text_raw = match.groups()
        clean_text = re.sub(r"<[^>]+>", "", text_raw).strip().replace("\r", "").replace("\n", " ")
        if clean_text:
            segments.append({
                "start": to_sec(s_str),
                "end": to_sec(e_str),
                "text": clean_text
            })
    duration = segments[-1]["end"] if segments else 0.0
    return {"duration": duration, "segments": segments}


def _try_fetch_native_youtube_subtitles(
    video_url: Optional[str],
    media_path: str,
    language: Optional[str] = None
) -> Optional[Dict]:
    """Check and extract native auto-caption or official subtitles in < 0.5s."""
    # 1. Check if yt-dlp downloaded any subtitle file (.vtt or .srt) alongside media_path
    if media_path:
        stem = Path(media_path).stem
        parent_dir = Path(media_path).parent
        langs_pref = [language] if language else ["id", "id-orig", "en", "en-orig"]
        def _sort_by_lang(path_obj: Path) -> int:
            fn = path_obj.name.lower()
            for idx, l in enumerate(langs_pref):
                if f".{l}." in fn or f"-{l}." in fn:
                    return idx
            return 999

        vtt_candidates = sorted(parent_dir.glob(f"{stem}*.vtt"), key=_sort_by_lang)
        for sub_file in vtt_candidates:
            try:
                with open(sub_file, "r", encoding="utf-8", errors="ignore") as f:
                    parsed = _parse_vtt_content(f.read())
                if parsed and parsed.get("segments"):
                    print(f"[transcribe/subtitles] Reused yt-dlp extracted VTT subtitle: {sub_file.name}", flush=True)
                    return parsed
            except Exception as e:
                print(f"[transcribe/subtitles] VTT parse notice: {e}", flush=True)

        srt_candidates = sorted(parent_dir.glob(f"{stem}*.srt"), key=_sort_by_lang)
        for sub_file in srt_candidates:
            try:
                parsed = _load_srt_cache(sub_file)
                if parsed and parsed.get("segments"):
                    print(f"[transcribe/subtitles] Reused yt-dlp extracted SRT subtitle: {sub_file.name}", flush=True)
                    return parsed
            except Exception as e:
                print(f"[transcribe/subtitles] SRT parse notice: {e}", flush=True)

    # 2. Query YouTubeTranscriptApi directly
    from .downloader import _extract_youtube_video_id
    vid = _extract_youtube_video_id(video_url or media_path)
    if vid:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            api = YouTubeTranscriptApi()
            t_list = api.list(vid)
            target_t = None
            langs = [language] if language else ["id", "id-orig", "en", "en-orig"]
            for l in langs:
                try:
                    target_t = t_list.find_transcript([l])
                    if target_t:
                        break
                except Exception:
                    pass
            if not target_t:
                target_t = next(iter(t_list), None)
            if target_t:
                data = target_t.fetch()
                segments = []
                for entry in data:
                    start = float(entry["start"] if isinstance(entry, dict) else getattr(entry, "start", 0.0))
                    dur = float((entry.get("duration", 2.0) if isinstance(entry, dict) else getattr(entry, "duration", 2.0)) or 2.0)
                    text = str(entry.get("text", "") if isinstance(entry, dict) else getattr(entry, "text", "")).strip().replace("\r", "").replace("\n", " ")
                    if text:
                        segments.append({"start": start, "end": round(start + dur, 3), "text": text})
                if segments:
                    duration = segments[-1]["end"]
                    print(f"[transcribe/youtube-api] Instant native captions fetched ({len(segments)} segments, {duration:.0f}s) in < 0.5s!", flush=True)
                    return {"duration": duration, "segments": segments}
        except Exception as e:
            print(f"[transcribe/youtube-api] YouTube native transcript note: {e}", flush=True)

        # 3. Fallback: yt-dlp native subtitle extraction (bypasses YouTubeTranscriptApi IP blocks / 429)
        try:
            from .downloader import _import_ytdlp
            yt_dlp = _import_ytdlp()
            target_url = video_url if (video_url and video_url.startswith("http")) else f"https://www.youtube.com/watch?v={vid}"

            if media_path and Path(media_path).parent.exists():
                out_dir = Path(media_path).parent
                out_stem = Path(media_path).stem
            else:
                out_dir = Path("output")
                out_dir.mkdir(parents=True, exist_ok=True)
                out_stem = f"source_{vid}"

            sub_template = str(out_dir / f"{out_stem}.%(ext)s")
            sub_langs = [language] if language else ["id", "id-orig", "en", "en-orig"]

            cookie_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "cookies.txt")
            ydl_sub_opts = {
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": sub_langs,
                "subtitlesformat": "vtt",
                "outtmpl": sub_template,
                "quiet": True,
                "no_warnings": True,
                "ignoreerrors": True,
            }
            if os.path.exists(cookie_file) and os.path.getsize(cookie_file) > 0:
                ydl_sub_opts["cookiefile"] = cookie_file

            print(f"[transcribe/yt-dlp-subs] Fetching YouTube subtitles for {vid} via yt-dlp...", flush=True)
            with yt_dlp.YoutubeDL(ydl_sub_opts) as ydl:
                ydl.download([target_url])

            vtt_matches = sorted(
                out_dir.glob(f"{out_stem}*.vtt"),
                key=lambda p: 0 if (language and f".{language}." in p.name.lower()) or (".id." in p.name.lower() or "-id." in p.name.lower()) else 1
            )
            for sub_file in vtt_matches:
                try:
                    with open(sub_file, "r", encoding="utf-8", errors="ignore") as f:
                        parsed = _parse_vtt_content(f.read())
                    if parsed and parsed.get("segments"):
                        print(f"[transcribe/subtitles] Extracted yt-dlp VTT subtitle: {sub_file.name} ({len(parsed['segments'])} segments)", flush=True)
                        return parsed
                except Exception as e:
                    print(f"[transcribe/subtitles] VTT parse notice: {e}", flush=True)
        except Exception as e:
            print(f"[transcribe/yt-dlp-subs] yt-dlp subtitle extraction notice: {e}", flush=True)

    return None


def transcribe_local(
    media_path: str,
    video_url: Optional[str] = None,
    language: Optional[str] = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Return a transcript for media_path.

    Sequence:
      1. Reuses cached transcript if valid.
      2. Checks YouTube native captions (YouTubeTranscriptApi / yt-dlp subtitles) in 0.5s.
      3. If no native captions, falls back to Groq Whisper Large v3 Turbo (runs in ~2-4s).
      4. Fallback to faster-whisper local if Groq not configured.
    """
    cache_path = _transcript_cache_path(media_path)
    if cache_path.exists():
        source_mtime = os.path.getmtime(media_path)
        cache_mtime = cache_path.stat().st_mtime
        if cache_mtime >= source_mtime:
            print(f"[transcribe/local] reusing cached transcript: {cache_path}", flush=True)
            cached = _load_srt_cache(cache_path)
            if not cached["segments"] or cached["duration"] <= 0.0:
                print(f"[transcribe/local] cache is empty/invalid, deleting: {cache_path}", flush=True)
                cache_path.unlink(missing_ok=True)
            else:
                print(
                    f"[transcribe/local] {len(cached['segments'])} cached segments, "
                    f"{cached['duration']:.0f}s of audio",
                    flush=True,
                )
                if on_status:
                    on_status("transcript_found")
                return cached

    # Step 1: Check YouTube native transcript
    if on_status:
        on_status("checking_transcript")

    native_transcript = _try_fetch_native_youtube_subtitles(video_url, media_path, language=language)
    if native_transcript and native_transcript.get("segments"):
        native_transcript["provider"] = "YouTube Subtitle Scraper"
        if on_status:
            on_status("transcript_found")
        _write_srt_cache(media_path, native_transcript)
        return native_transcript

    # Step 2: Native not found, fallback to Groq Whisper
    if on_status:
        on_status("transcribing_groq")

    provider = (LOCAL_TRANSCRIBE_PROVIDER or "groq").strip().lower()
    if provider == "groq":
        transcript = _transcribe_local_groq(media_path, language=language, on_status=on_status)
        transcript["provider"] = "Groq Cloud Whisper"
    elif provider == "gemini":
        transcript = _transcribe_local_gemini(media_path, language=language, on_status=on_status)
        transcript["provider"] = "Gemini AI"
    elif provider == "whisper":
        transcript = _transcribe_local_whisper(media_path, language=language)
        transcript["provider"] = "Faster-Whisper Local"
    else:
        raise RuntimeError(
            f"Unknown LOCAL_TRANSCRIBE_PROVIDER={provider!r}. Use 'groq', 'gemini', or 'whisper'."
        )

    cache_path = _write_srt_cache(media_path, transcript)
    print(f"[transcribe/local] wrote cache: {cache_path} (provider: {transcript.get('provider')})", flush=True)
    return transcript


GROQ_FREE_TIER_MAX_BYTES = 25 * 1024 * 1024  # 25MB, Groq free-tier upload limit


def _extract_compressed_audio(media_path: str, out_path: str) -> None:
    """Extract audio-only, mono 16kHz Opus at a low bitrate.

    This is what keeps the upload small enough for Groq's free-tier 25MB
    limit — sending the raw video (or even raw-quality audio) blows past it
    on anything longer than a few minutes. Speech recognition doesn't need
    music-quality audio, so a low bitrate here costs nothing in practice.
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", media_path,
        "-vn",  # no video
        "-ac", "1",  # mono
        "-ar", "16000",  # 16kHz
        "-c:a", "libopus", "-b:a", "24k",
        out_path,
    ]
    subprocess.run(cmd, check=True)


def _transcribe_local_groq(
    media_path: str,
    language: Optional[str] = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Transcribe via Groq's hosted Whisper Large v3 Turbo (fast, needs GROQ_API_KEY).

    on_status, if given, is called with short human-readable status strings
    ("extracting_audio", "uploading") so the caller (e.g. the web app)
    can show progress without this module knowing anything about the caller UI.
    """
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai is required for LOCAL_TRANSCRIBE_PROVIDER=groq (used as the client "
            "for Groq's OpenAI-compatible API). Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    from ..config import GROQ_BASE_URL, GROQ_WHISPER_MODEL, require_groq_key

    if on_status:
        on_status("extracting_audio")

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio.ogg")
        _extract_compressed_audio(media_path, audio_path)

        audio_size = os.path.getsize(audio_path)
        print(f"[transcribe/local] extracted audio: {audio_size / 1024 / 1024:.1f} MB", flush=True)

        if audio_size > GROQ_FREE_TIER_MAX_BYTES:
            raise RuntimeError(
                f"Extracted audio ({audio_size / 1024 / 1024:.1f} MB) still exceeds "
                f"batas upload Groq free tier (25 MB). Videonya kemungkinan terlalu panjang "
                f"for cloud transcription — set LOCAL_TRANSCRIBE_PROVIDER=whisper in "
                f".env for local transcription, or use a shorter video."
            )

        if on_status:
            on_status("uploading")

        print(f"[transcribe/local] groq model={GROQ_WHISPER_MODEL}", flush=True)
        client = OpenAI(api_key=require_groq_key(), base_url=GROQ_BASE_URL)

        with open(audio_path, "rb") as f:
            response = client.audio.transcriptions.create(
                file=f,
                model=GROQ_WHISPER_MODEL,
                language=language,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

    raw_segments = getattr(response, "segments", None) or []
    segments = [
        {
            "start": float(s["start"] if isinstance(s, dict) else s.start),
            "end": float(s["end"] if isinstance(s, dict) else s.end),
            "text": str(s["text"] if isinstance(s, dict) else s.text).strip(),
        }
        for s in raw_segments
    ]
    duration = float(getattr(response, "duration", 0.0) or 0.0) or (
        segments[-1]["end"] if segments else 0.0
    )
    print(f"[transcribe/local] {len(segments)} segments, {duration:.0f}s of audio (groq)", flush=True)
    return {"duration": duration, "segments": segments}



def _transcribe_local_whisper(media_path: str, language: Optional[str] = None) -> Dict:
    """Run faster-whisper on this machine (CPU or CUDA GPU if available)."""

    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    device = _resolve_device()
    compute_type = "float16" if device == "cuda" else "int8"
    print(f"[transcribe/local] faster-whisper model={LOCAL_WHISPER_MODEL} device={device}", flush=True)

    from ..config import LOCAL_WHISPER_VAD_FILTER, LOCAL_WHISPER_VAD_PARAMETERS

    model = WhisperModel(LOCAL_WHISPER_MODEL, device=device, compute_type=compute_type)

    transcribe_kwargs = {
        "audio": media_path,
        "language": language,
        "beam_size": 5,
        "condition_on_previous_text": False,
    }
    if LOCAL_WHISPER_VAD_FILTER:
        transcribe_kwargs["vad_filter"] = True
        transcribe_kwargs["vad_parameters"] = LOCAL_WHISPER_VAD_PARAMETERS
    else:
        transcribe_kwargs["vad_filter"] = False

    segments_iter, info = model.transcribe(**transcribe_kwargs)

    segments = []
    import tempfile
    prog_file = os.path.join(tempfile.gettempdir(), "ai_transcribe_progress.txt")
    try: os.remove(prog_file)
    except: pass
    
    total_dur = getattr(info, "duration", 0.0)
    for s in segments_iter:
        if total_dur > 0:
            pct = (float(s.end) / float(total_dur)) * 100
            try:
                with open(prog_file, "w") as f:
                    f.write(f"{pct:.1f},{s.end:.1f},{total_dur:.1f}")
            except: pass
            print(f"[transcribe/local] {s.end:.1f}s / {total_dur:.1f}s ({pct:.1f}%)", flush=True)

        segments.append({
            "start": float(s.start),
            "end": float(s.end),
            "text": (s.text or "").strip(),
        })

    duration = float(getattr(info, "duration", 0.0)) or (segments[-1]["end"] if segments else 0.0)
    print(f"[transcribe/local] {len(segments)} segments, {duration:.0f}s of audio", flush=True)
    return {"duration": duration, "segments": segments}


def _transcribe_local_gemini(
    media_path: str,
    language: Optional[str] = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Transcribe audio using Gemini Multimodal Audio API."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LOCAL_TRANSCRIBE_PROVIDER=gemini. Install it with:\n"
            "    pip install google-genai"
        ) from e

    if on_status:
        on_status("extracting_audio")

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio.mp3")
        # Extract audio as 16kHz mono MP3
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", media_path,
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "libmp3lame", "-b:a", "64k",
            audio_path,
        ]
        subprocess.run(cmd, check=True)

        audio_size = os.path.getsize(audio_path)
        print(f"[transcribe/gemini] extracted audio: {audio_size / 1024 / 1024:.1f} MB", flush=True)

        if on_status:
            on_status("uploading")

        client = genai.Client(api_key=require_gemini_key())
        print("[transcribe/gemini] uploading audio to Gemini Files API...", flush=True)
        uploaded_file = client.files.upload(file=audio_path)

        # Wait for file to become ACTIVE if still processing
        import time
        for _ in range(30):
            if not uploaded_file.state or uploaded_file.state.name == "ACTIVE":
                break
            if uploaded_file.state.name == "FAILED":
                raise RuntimeError("Gemini audio file processing failed on server.")
            print("[transcribe/gemini] waiting for audio file to be ready...", flush=True)
            time.sleep(2)
            uploaded_file = client.files.get(name=uploaded_file.name)

        if on_status:
            on_status("transcribing_gemini")

        lang_instruction = f" The audio language is {language}." if language else ""
        prompt = f"""Transcribe this audio file verbatim with accurate timestamps for each sentence or dialogue segment.{lang_instruction}

Return a valid JSON object matching this schema:
{{
  "duration": <total duration in seconds as float>,
  "segments": [
    {{
      "start": <start timestamp in seconds as float>,
      "end": <end timestamp in seconds as float>,
      "text": "<transcribed text for this segment>"
    }}
  ]
}}

Rules:
- Capture every spoken sentence verbatim with natural sentence breaks.
- Ensure 'start' and 'end' are numbers in seconds (e.g. 0.0, 14.5).
- Do not skip parts of the audio or summarize.
- Output pure JSON only.
"""

        print(f"[transcribe/gemini] generating transcription with model={GEMINI_MODEL} (this may take 15-45s)...", flush=True)
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL or "gemini-3.5-flash",
                contents=[uploaded_file, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=8192,
                ),
            )
            raw_text = response.text or "{}"
            clean_json = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.MULTILINE)
            clean_json = re.sub(r"\s*```$", "", clean_json.strip(), flags=re.MULTILINE)
            data = json.loads(clean_json)
        finally:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception as e:
                print(f"[transcribe/gemini] warning deleting remote file: {e}", flush=True)

    segments = []
    for s in data.get("segments", []):
        try:
            start = float(s.get("start", 0.0))
            end = float(s.get("end", 0.0))
            text = str(s.get("text", "")).strip()
            if text and end > start:
                segments.append({"start": start, "end": end, "text": text})
        except (ValueError, TypeError):
            continue

    duration = float(data.get("duration", 0.0))
    if duration <= 0.0 and segments:
        duration = segments[-1]["end"]

    print(f"[transcribe/gemini] {len(segments)} segments, {duration:.0f}s of audio (gemini)", flush=True)
    return {"duration": duration, "segments": segments}
