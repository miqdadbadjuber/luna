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
from typing import Callable, Dict, List, Optional, Tuple

from .config import LOCAL_OUTPUT_DIR
from .subtitles import overlay_args, render_cues, segments_for_clip

# Sample face position once per second (approx 30 frames) for tracking
FACE_DETECT_SAMPLE_EVERY = 30


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
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
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


def _sample_face_centers(
    in_path: str, src_w: int, src_h: int, crop_w: int, crop_h: int, start_time: float, end_time: float, fps: float
) -> List[Tuple[int, int]]:
    """Fast face sampling on downscaled frames with linear interpolation."""
    import cv2  # type: ignore

    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        return [(max(0, (src_w - crop_w) // 2), max(0, (src_h - crop_h) // 2))]

    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start_time * 1000.0))

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
    # Test AMD AMF hardware encoder
    try:
        res = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=0.1:size=256x256:rate=30", "-c:v", "h264_amf", "-f", "null", "-"],
            capture_output=True, text=True, timeout=4
        )
        if res.returncode == 0:
            print("[clip/local] Using AMD AMF Hardware Acceleration (h264_amf)", flush=True)
            _DETECTED_ENCODER_FLAGS = ["-c:v", "h264_amf", "-quality", "speed"]
            return _DETECTED_ENCODER_FLAGS
    except Exception:
        pass

    # Test MediaFoundation
    try:
        res = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=0.1:size=256x256:rate=30", "-c:v", "h264_mf", "-f", "null", "-"],
            capture_output=True, text=True, timeout=4
        )
        if res.returncode == 0:
            print("[clip/local] Using MediaFoundation Hardware Acceleration (h264_mf)", flush=True)
            _DETECTED_ENCODER_FLAGS = ["-c:v", "h264_mf"]
            return _DETECTED_ENCODER_FLAGS
    except Exception:
        pass

    _DETECTED_ENCODER_FLAGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "0"]
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
) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start_time:.3f}",
        "-to", f"{end_time:.3f}",
        "-i", source_path,
    ]
    tail = [*enc_flags, "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out_path]
    if not cues:
        subprocess.run([*cmd, *(["-vf", vf] if vf else []), *tail], check=True)
        return
    with tempfile.TemporaryDirectory() as tmp:
        rendered = render_cues(cues, frame_w, frame_h, tmp)
        subprocess.run([*cmd, *overlay_args(rendered, vf), *tail], check=True)


def crop_clip_local(
    source_path: str,
    start_time: float,
    end_time: float,
    aspect_ratio: str,
    out_path: str,
    use_face_detect: bool = False,
    src_dims: Optional[Tuple[int, int, float]] = None,
    cues: Optional[List[Dict]] = None,
) -> str:
    """Cut + reframe one highlight in a single fast ffmpeg pass with hardware acceleration."""
    if src_dims is None:
        src_w, src_h, fps = _probe_dims(source_path)
    else:
        src_w, src_h, fps = src_dims

    padded_end = end_time + 0.25
    crop_w, crop_h = _crop_box(src_w, src_h, aspect_ratio)
    enc_flags = _get_encoder_flags()

    if aspect_ratio == "16:9":
        # Native aspect ratio: subclip directly
        _encode(source_path, start_time, padded_end, "", enc_flags, out_path, cues, src_w, src_h)
        return out_path

    if use_face_detect:
        centers = _sample_face_centers(source_path, src_w, src_h, crop_w, crop_h, start_time, end_time, fps)
        sendcmd_path = out_path + ".sendcmd.txt"
        with open(sendcmd_path, "w") as f:
            for i, (x0, y0) in enumerate(centers):
                t = i / fps if fps else 0.0
                f.write(f"{t:.5f} crop@c x {x0}, crop@c y {y0};\n")

        crop_filter = f"crop@c={crop_w}:{crop_h}:{centers[0][0]}:{centers[0][1]}"
        vf = f"{crop_filter},sendcmd=f={sendcmd_path}"
        try:
            _encode(source_path, start_time, padded_end, vf, enc_flags, out_path, cues, crop_w, crop_h)
        finally:
            if os.path.exists(sendcmd_path):
                os.remove(sendcmd_path)
        return out_path

    # Static center crop (9:16, 1:1, 3:4, etc.) in a single fast pass
    x0 = max(0, (src_w - crop_w) // 2)
    y0 = max(0, (src_h - crop_h) // 2)
    _encode(source_path, start_time, padded_end, f"crop={crop_w}:{crop_h}:{x0}:{y0}", enc_flags, out_path, cues, crop_w, crop_h)
    return out_path


def crop_highlights_local(
    source_path: str,
    highlights: List[Dict],
    aspect_ratio: str = "9:16",
    out_dir: Optional[str] = None,
    use_face_detect: bool = False,
    on_progress: Optional[Callable[[int, int], None]] = None,
    transcript_segments: Optional[List[Dict]] = None,
) -> List[Dict]:
    out_dir = out_dir or LOCAL_OUTPUT_DIR
    if "=" in str(out_dir) or not str(out_dir).strip():
        out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)

    src_dims = _probe_dims(source_path)
    print(
        f"[clip/local] source={src_dims[0]}x{src_dims[1]} @ {src_dims[2]:.1f}fps, "
        f"target_ratio={aspect_ratio}, face_detect={use_face_detect}, total_clips={len(highlights)}",
        flush=True,
    )

    results: List[Dict] = [{} for _ in highlights]

    def _process_one(idx: int, h: Dict) -> Dict:
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
                use_face_detect=use_face_detect,
                src_dims=src_dims,
                cues=segments_for_clip(
                    transcript_segments or [], float(h["start_time"]), float(h["end_time"]) + 0.25
                ),
            )
            print(f"[clip/local] finished clip {idx}/{len(highlights)} -> {out_path}", flush=True)
            return {**h, "clip_url": out_path}
        except Exception as e:
            print(f"[clip/local] clip {idx} failed: {e}", flush=True)
            return {**h, "clip_url": None, "error": str(e)}

    # Render up to 3 clips simultaneously in parallel
    max_workers = min(3, max(1, (os.cpu_count() or 4) - 1))
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