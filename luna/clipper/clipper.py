# SPDX-License-Identifier: MIT
# This file is part of Luna's clip pipeline. See luna/clipper/LICENSE and
# THIRD_PARTY_NOTICES.md for the upstream notice.

"""Local clipping: ultra-fast single-pass ffmpeg subclip + crop in parallel.

Optimizations:
  1. Single-pass FFmpeg: Subclip seek (-ss/-to) and aspect ratio crop (-vf crop)
     are executed in a single FFmpeg encode, eliminating the slow 2-stage
     intermediate file encode.
  2. Multi-threaded encoding: Uses `-preset veryfast -threads 0 -crf 20` for
     maximum speed with crisp HD quality.
  3. Parallel clip processing: Clips are rendered concurrently across CPU cores
     using ThreadPoolExecutor, speeding up 5-clip generation by 5x-10x.
"""
import concurrent.futures
import os
import subprocess
import tempfile
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from .config import local_output_dir
from .subtitles import MAX_INLINE_OVERLAY_SCREENS, overlay_args, overlay_args_script, render_cues, segments_for_clip

# Sample face position once per second (approx 30 frames) for tracking
FACE_DETECT_SAMPLE_EVERY = 30

# Ceiling for long/non-clip ffmpeg calls; individual clip encodes use a tighter duration-based budget.
FFMPEG_TIMEOUT_SECONDS = 3600

_HARDWARE_ENCODERS = ("h264_nvenc", "h264_amf", "h264_qsv", "h264_mf")
_SOFTWARE_ENCODER_FLAGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "0"]

# Hardware encoder candidates ordered by quality/speed reliability. Every candidate carries
# explicit rate-control / quality flags (never bare `-c:v h264_mf`, which defaults to ~200-350 kbps).
_HARDWARE_ENCODER_CANDIDATES: Tuple[Tuple[str, List[str]], ...] = (
    (
        "NVIDIA NVENC Hardware Acceleration (h264_nvenc)",
        ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "20", "-b:v", "0"],
    ),
    (
        "AMD AMF Hardware Acceleration (h264_amf)",
        ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "20", "-qp_p", "20"],
    ),
    (
        "Intel QSV Hardware Acceleration (h264_qsv)",
        ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "20"],
    ),
    (
        "MediaFoundation Hardware Acceleration (h264_mf)",
        ["-c:v", "h264_mf", "-rate_control", "quality", "-quality", "80"],
    ),
    (
        "MediaFoundation Hardware Acceleration (h264_mf VBR)",
        ["-c:v", "h264_mf", "-rate_control", "pc_vbr", "-b:v", "5M", "-maxrate", "8M"],
    ),
)


def _is_hardware_encoder(enc_flags: List[str]) -> bool:
    return any(codec in enc_flags for codec in _HARDWARE_ENCODERS)


def _run_ffmpeg(
    cmd: List[str],
    timeout: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
) -> subprocess.CompletedProcess:
    """Run ffmpeg/ffprobe with timeout + cancel_event polling and return CompletedProcess."""
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("CANCELLED_BY_USER")

    limit = max(10.0, float(timeout or FFMPEG_TIMEOUT_SECONDS))
    deadline = time.monotonic() + limit
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    while True:
        if cancel_event is not None and cancel_event.is_set():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise RuntimeError("CANCELLED_BY_USER")
        try:
            out, err = proc.communicate(timeout=1)
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() > deadline:
                proc.kill()
                proc.communicate()
                raise RuntimeError(f"ffmpeg timed out after {int(limit)}s")

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {(err or '')[-2000:]}")
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout=out, stderr=err)


def _ratio(aspect_ratio: str) -> float:
    """Parse '9:16' → 9/16, '1:1' → 1.0."""
    try:
        w, h = aspect_ratio.split(":")
        return float(w) / float(h)
    except (ValueError, ZeroDivisionError):
        return 9.0 / 16.0


def _probe_dims(path: str) -> Tuple[int, int, float]:
    """Return (width, height, fps) via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "csv=p=0",
        path,
    ]
    out = _run_ffmpeg(cmd, timeout=60).stdout.strip()
    w_str, h_str, fps_str = out.split(",")
    width, height = int(w_str), int(h_str)
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 30.0
    else:
        fps = float(fps_str) if fps_str else 30.0
    return width, height, fps


def _crop_box(src_w: int, src_h: int, aspect_ratio: str) -> Tuple[int, int]:
    """Largest crop_w x crop_h that fits inside the source frame at target ratio."""
    target_ratio = _ratio(aspect_ratio)
    if target_ratio < src_w / src_h:
        crop_h = src_h
        crop_w = int(crop_h * target_ratio)
    else:
        crop_w = src_w
        crop_h = int(crop_w / target_ratio)
    crop_w = max(2, crop_w - (crop_w % 2))
    crop_h = max(2, crop_h - (crop_h % 2))
    return crop_w, crop_h


def _escape_filter_path(path: str) -> str:
    """Escape a filesystem path so it can sit inside an ffmpeg filtergraph value.

    ffmpeg's filter parser treats backslash, colon, quote, comma, brackets and
    semicolon as syntax, so a raw Windows path like C:\\temp\\x.txt tears the
    graph apart. Normalise separators to forward slashes, backslash-escape the
    rest, then wrap the whole value in single quotes.
    """
    escaped = str(path).replace("\\", "/")
    for char in ("\\", ":", "'", ",", "[", "]", ";"):
        escaped = escaped.replace(char, "\\" + char)
    return f"'{escaped}'"


def _apply_thread_budget(enc_flags: List[str], threads: int) -> List[str]:
    """Replace the encoder's thread count with one worker's share of the CPU budget."""
    flags = list(enc_flags)
    if "-threads" not in flags:
        # hardware encoders size their own pools, so leave those flags untouched
        return flags
    flags[flags.index("-threads") + 1] = str(max(1, threads))
    return flags


def _sample_face_centers(
    in_path: str, src_w: int, src_h: int, crop_w: int, crop_h: int, start_time: float, end_time: float, fps: float
) -> List[Tuple[int, int]]:
    """Fast face sampling on downscaled frames with linear interpolation."""
    # same fallback the tracker already uses when the file cannot be opened:
    # a missing cv2 or Haar cascade must not abort the clip, the static center
    # crop still runs. The caller expects crop ORIGINS, not centres, so convert here.
    static_origin = (
        max(0, (src_w - crop_w) // 2),
        max(0, (src_h - crop_h) // 2),
    )
    try:
        import cv2  # type: ignore
    except Exception as e:
        print(f"[clip/local] face detect unavailable ({e}), using static center crop", flush=True)
        return [static_origin]

    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        return [static_origin]

    try:
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if face_cascade.empty():
            print("[clip/local] Haar cascade missing, using static center crop", flush=True)
            cap.release()
            return [static_origin]
    except Exception as e:
        print(f"[clip/local] Haar cascade unavailable ({e}), using static center crop", flush=True)
        cap.release()
        return [static_origin]

    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start_time * 1000.0))
    # the seek lands on the nearest keyframe before start_time, so drop frames
    # until the read head reaches the clip start; capped at ~10s of frames so a
    # backend that never reports POS_MSEC cannot stall the whole encode
    target_ms = max(0.0, start_time * 1000.0)
    for _ in range(300):
        if cap.get(cv2.CAP_PROP_POS_MSEC) >= target_ms:
            break
        if not cap.grab():
            break

    total_frames = int(max(1.0, (end_time - start_time) * (fps or 30.0)))
    sample_idxs: List[int] = []
    sample_centers: List[Tuple[int, int]] = []
    default_center = (src_w // 2, src_h // 2)
    last_center = default_center

    frame_idx = 0
    scale = 360.0 / max(1, src_h) if src_h > 360 else 1.0

    while frame_idx < total_frames:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % FACE_DETECT_SAMPLE_EVERY == 0:
            if scale != 1.0:
                small = cv2.resize(frame, (int(src_w * scale), int(src_h * scale)), interpolation=cv2.INTER_LINEAR)
            else:
                small = frame
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4, minSize=(30, 30))
            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                last_center = (int((x + w // 2) / scale), int((y + h // 2) / scale))
            sample_idxs.append(frame_idx)
            sample_centers.append(last_center)
        frame_idx += 1
    cap.release()

    if not sample_idxs:
        sample_idxs = [0]
        sample_centers = [default_center]

    centers: List[Tuple[int, int]] = []
    actual_frames = max(1, frame_idx)
    for f in range(actual_frames):
        if f <= sample_idxs[0]:
            cx, cy = sample_centers[0]
        elif f >= sample_idxs[-1]:
            cx, cy = sample_centers[-1]
        else:
            cx, cy = sample_centers[-1]
            for i in range(len(sample_idxs) - 1):
                a, b = sample_idxs[i], sample_idxs[i + 1]
                if a <= f <= b:
                    t = (f - a) / (b - a) if b != a else 0.0
                    ax, ay = sample_centers[i]
                    bx, by = sample_centers[i + 1]
                    cx = int(ax + (bx - ax) * t)
                    cy = int(ay + (by - ay) * t)
                    break
        x0 = max(0, min(src_w - crop_w, cx - crop_w // 2))
        y0 = max(0, min(src_h - crop_h, cy - crop_h // 2))
        centers.append((x0, y0))

    return centers


_DETECTED_ENCODER_FLAGS: Optional[List[str]] = None


def _get_encoder_flags() -> List[str]:
    global _DETECTED_ENCODER_FLAGS
    if _DETECTED_ENCODER_FLAGS is not None:
        return _DETECTED_ENCODER_FLAGS

    # Probe each candidate with its exact quality/rate-control flags so unsupported driver modes
    # fall through cleanly instead of encoding blurry ~200 kbps defaults or failing mid-clip.
    for label, flags in _HARDWARE_ENCODER_CANDIDATES:
        try:
            res = subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", "testsrc=duration=0.1:size=256x256:rate=30",
                    *flags,
                    "-pix_fmt", "yuv420p",
                    "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=4,
            )
            if res.returncode == 0:
                print(f"[clip/local] Using {label}", flush=True)
                _DETECTED_ENCODER_FLAGS = list(flags)
                return _DETECTED_ENCODER_FLAGS
        except Exception:
            pass

    _DETECTED_ENCODER_FLAGS = list(_SOFTWARE_ENCODER_FLAGS)
    return _DETECTED_ENCODER_FLAGS


def _encode(
    source_path: str,
    start_time: float,
    end_time: float,
    vf: str,
    enc_flags: List[str],
    out_path: str,
    cues: Optional[List[Dict]],
    frame_w: int,
    frame_h: int,
    worker_threads: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    clip_dur = max(0.1, end_time - start_time)
    clip_timeout = max(180.0, clip_dur * 5.0 + 60.0)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start_time:.3f}",
        # -t is the clip length, which is unambiguous; -to depends on whether
        # ffmpeg reads it as an input or output timestamp
        "-t", f"{clip_dur:.3f}",
        "-i", source_path,
    ]

    def _encode_with(flags: List[str]) -> None:
        resolved_flags = _apply_thread_budget(flags, worker_threads) if worker_threads else list(flags)
        tail = [
            *resolved_flags, "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",  # 10-bit/HDR sources otherwise produce unplayable clips
            "-movflags", "+faststart", out_path,
        ]
        if not cues:
            _run_ffmpeg([*cmd, *(["-vf", vf] if vf else []), *tail], timeout=clip_timeout, cancel_event=cancel_event)
            return
        with tempfile.TemporaryDirectory() as tmp:
            rendered = render_cues(cues, frame_w, frame_h, tmp)
            if len(rendered) > MAX_INLINE_OVERLAY_SCREENS:
                # one -i per cue plus the inline graph overruns the Windows command
                # line; the graph goes in a script file that TemporaryDirectory clears
                script_path = os.path.join(tmp, "filtergraph.txt")
                _run_ffmpeg([*cmd, *overlay_args_script(rendered, vf, script_path), *tail], timeout=clip_timeout, cancel_event=cancel_event)
            else:
                _run_ffmpeg([*cmd, *overlay_args(rendered, vf), *tail], timeout=clip_timeout, cancel_event=cancel_event)

    try:
        _encode_with(enc_flags)
    except Exception as exc:
        if (cancel_event is not None and cancel_event.is_set()) or str(exc) == "CANCELLED_BY_USER":
            raise
        if not _is_hardware_encoder(enc_flags):
            raise
        # Hardware drivers (e.g. h264_amf) can hang or fail mid-stream; discard partial MP4 and fall back cleanly.
        print(f"[clip/local] hardware encode failed ({exc}), retrying with libx264", flush=True)
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        _encode_with(_SOFTWARE_ENCODER_FLAGS)


def crop_clip_local(
    source_path: str,
    start_time: float,
    end_time: float,
    aspect_ratio: str,
    out_path: str,
    use_face_detect: bool = False,
    src_dims: Optional[Tuple[int, int, float]] = None,
    cues: Optional[List[Dict]] = None,
    worker_threads: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Cut + reframe one highlight in a single fast ffmpeg pass with hardware acceleration."""
    if src_dims is None:
        src_w, src_h, fps = _probe_dims(source_path)
    else:
        src_w, src_h, fps = src_dims

    padded_end = end_time + 0.25
    crop_w, crop_h = _crop_box(src_w, src_h, aspect_ratio)
    enc_flags = _get_encoder_flags()

    if aspect_ratio in ("16:9", "original"):
        # Native aspect ratio: subclip directly (face tracking has no crop slack)
        _encode(
            source_path, start_time, padded_end, "", enc_flags, out_path, cues,
            src_w, src_h, worker_threads=worker_threads, cancel_event=cancel_event,
        )
        return out_path

    if use_face_detect:
        centers = _sample_face_centers(source_path, src_w, src_h, crop_w, crop_h, start_time, end_time, fps)
        sendcmd_path = out_path + ".sendcmd.txt"
        with open(sendcmd_path, "w") as f:
            for i, (x0, y0) in enumerate(centers):
                t = i / fps if fps else 0.0
                f.write(f"{t:.5f} crop@c x {x0}, crop@c y {y0};\n")

        crop_filter = f"crop@c={crop_w}:{crop_h}:{centers[0][0]}:{centers[0][1]}"
        escaped_path = _escape_filter_path(sendcmd_path)
        if "\n" in escaped_path or "\r" in escaped_path:
            # a path we cannot express inside a filtergraph must not kill the clip
            print("[clip/local] sendcmd path is not filter-safe, using static center crop", flush=True)
            if os.path.exists(sendcmd_path):
                os.remove(sendcmd_path)
        else:
            vf = f"{crop_filter},sendcmd=f={escaped_path}"
            try:
                _encode(
                    source_path, start_time, padded_end, vf, enc_flags, out_path, cues, crop_w, crop_h,
                    worker_threads=worker_threads, cancel_event=cancel_event,
                )
            finally:
                if os.path.exists(sendcmd_path):
                    os.remove(sendcmd_path)
            return out_path

    # Static center crop (9:16, 1:1, 3:4, etc.) in a single fast pass
    x0 = max(0, (src_w - crop_w) // 2)
    y0 = max(0, (src_h - crop_h) // 2)
    _encode(
        source_path, start_time, padded_end, f"crop={crop_w}:{crop_h}:{x0}:{y0}", enc_flags, out_path, cues,
        crop_w, crop_h, worker_threads=worker_threads, cancel_event=cancel_event,
    )
    return out_path


def crop_highlights_local(
    source_path: str,
    highlights: List[Dict],
    aspect_ratio: str = "9:16",
    out_dir: Optional[str] = None,
    use_face_detect: bool = False,
    on_progress: Optional[Callable[[int, int], None]] = None,
    transcript_segments: Optional[List[Dict]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> List[Dict]:
    out_dir = out_dir or local_output_dir()
    if "=" in str(out_dir) or not str(out_dir).strip():
        out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)

    src_dims = _probe_dims(source_path)
    enc_flags = _get_encoder_flags()
    effective_face_detect = bool(use_face_detect and aspect_ratio not in ("16:9", "original"))
    print(
        f"[clip/local] source={src_dims[0]}x{src_dims[1]} @ {src_dims[2]:.1f}fps, "
        f"target_ratio={aspect_ratio}, face_detect={effective_face_detect}, total_clips={len(highlights)}",
        flush=True,
    )

    results: List[Dict] = [{} for _ in highlights]
    # GPU hardware encoders (AMD AMF / MediaFoundation) can deadlock under concurrent encodes,
    # so serialize hardware jobs while keeping multi-worker encoding for software libx264.
    if _is_hardware_encoder(enc_flags):
        max_workers = 1
        worker_threads = 0
    else:
        max_workers = min(3, max(1, (os.cpu_count() or 4) - 1))
        # a single worker keeps libx264's own -threads 0 detection, otherwise it
        # would oversubscribe the CPU across parallel ffmpeg processes
        worker_threads = max(1, (os.cpu_count() or 4) // max_workers) if max_workers > 1 else 0

    def _process_one(idx: int, h: Dict) -> Dict:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("CANCELLED_BY_USER")
        out_path = os.path.join(out_dir, f"short_{idx:02d}.mp4")
        print(
            f"[clip/local] starting clip {idx}/{len(highlights)}: {h.get('title', '(untitled)')} "
            f"[{float(h['start_time']):.1f}s - {float(h['end_time']):.1f}s]",
            flush=True,
        )
        try:
            crop_clip_local(
                source_path,
                float(h["start_time"]),
                float(h["end_time"]),
                aspect_ratio,
                out_path,
                use_face_detect=effective_face_detect,
                src_dims=src_dims,
                cues=segments_for_clip(
                    transcript_segments or [], float(h["start_time"]), float(h["end_time"]) + 0.25
                ),
                worker_threads=worker_threads,
                cancel_event=cancel_event,
            )
            print(f"[clip/local] finished clip {idx}/{len(highlights)} -> {out_path}", flush=True)
            return {**h, "clip_url": out_path}
        except Exception as e:
            if (cancel_event is not None and cancel_event.is_set()) or str(e) == "CANCELLED_BY_USER":
                raise RuntimeError("CANCELLED_BY_USER") from e
            print(f"[clip/local] clip {idx} failed: {e}", flush=True)
            return {**h, "clip_url": None, "error": str(e)}

    completed_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_one, i, h): i - 1 for i, h in enumerate(highlights, 1)}
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
            completed_count += 1
            if on_progress:
                on_progress(completed_count, len(highlights))

    return results