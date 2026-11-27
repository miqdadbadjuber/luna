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
import math
import os
import subprocess
import tempfile
import threading
import time
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from .config import local_output_dir
from .subtitles import MAX_INLINE_OVERLAY_SCREENS, overlay_args, overlay_args_script, render_cues, segments_for_clip

# Sample face position at 6 fps for smooth, responsive tracking across shots
FACE_DETECT_SAMPLE_EVERY = 30
FACE_TRACK_SAMPLE_FPS = 6.0
_YUNET_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "models",
    "face_detection_yunet_2023mar.onnx",
)

# Ceiling for long/non-clip ffmpeg calls; individual clip encodes use a tighter duration-based budget.
FFMPEG_TIMEOUT_SECONDS = 3600

_HARDWARE_ENCODERS = ("h264_nvenc", "h264_amf", "h264_qsv", "h264_mf")
_SERIAL_HARDWARE_ENCODERS = ("h264_amf", "h264_mf")
_SOFTWARE_ENCODER_FLAGS = ["-c:v", "libx264", "-preset", "superfast", "-crf", "21", "-threads", "0"]

# Hardware encoder candidates ordered by quality/speed reliability. Every candidate carries
# explicit rate-control / quality flags (never bare `-c:v h264_mf`, which defaults to ~200-350 kbps),
# and `h264_mf` requires `-hw_encoding 1` so CPU-only VMs / Windows PCs do not pick Microsoft's
# slow software MFT and accidentally serialize all clip renders.
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
        ["-c:v", "h264_mf", "-hw_encoding", "1", "-rate_control", "quality", "-quality", "80"],
    ),
    (
        "MediaFoundation Hardware Acceleration (h264_mf VBR)",
        ["-c:v", "h264_mf", "-hw_encoding", "1", "-rate_control", "pc_vbr", "-b:v", "5M", "-maxrate", "8M"],
    ),
)


def _is_hardware_encoder(enc_flags: List[str]) -> bool:
    return any(codec in enc_flags for codec in _HARDWARE_ENCODERS)


def _is_serial_hardware_encoder(enc_flags: List[str]) -> bool:
    return any(codec in enc_flags for codec in _SERIAL_HARDWARE_ENCODERS)


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


def _create_face_detector(cv2_mod, det_w: int, det_h: int) -> Tuple[Optional[str], object]:
    """Create a per-clip face detector, preferring bundled YuNet ONNX with Haar fallback."""
    if os.path.isfile(_YUNET_MODEL_PATH) and hasattr(cv2_mod, "FaceDetectorYN"):
        try:
            detector = cv2_mod.FaceDetectorYN.create(
                _YUNET_MODEL_PATH,
                "",
                (det_w, det_h),
                score_threshold=0.68,
                nms_threshold=0.3,
                top_k=10,
            )
            if detector is not None:
                return "yunet", detector
        except Exception as exc:
            print(f"[clip/local] YuNet init failed ({exc}), falling back to Haar cascade", flush=True)

    try:
        cascade = cv2_mod.CascadeClassifier(
            cv2_mod.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        if not cascade.empty():
            return "haar", cascade
    except Exception as exc:
        print(f"[clip/local] Haar cascade unavailable ({exc})", flush=True)
    return None, None


def _detect_faces_in_frame(
    cv2_mod,
    detector_kind: Optional[str],
    detector: object,
    frame,
    gray,
    det_w: int,
    det_h: int,
    src_w: int,
    src_h: int,
    crop_h: int,
) -> List[Dict]:
    """Detect faces and return source-space targets with detection-space mouth boxes."""
    scale_x = det_w / float(max(1, src_w))
    scale_y = det_h / float(max(1, src_h))
    results: List[Dict] = []

    if detector_kind == "yunet" and detector is not None:
        try:
            detector.setInputSize((det_w, det_h))
            _, raw_faces = detector.detect(frame)
        except Exception:
            raw_faces = None
        if raw_faces is not None and len(raw_faces) > 0:
            for row in raw_faces:
                x, y, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
                score = float(row[14]) if len(row) >= 15 else 0.75
                if w < 12.0 or h < 12.0 or score < 0.68:
                    continue
                re_x, re_y = float(row[4]), float(row[5])
                le_x, le_y = float(row[6]), float(row[7])
                nose_x = float(row[8])
                rm_x, rm_y = float(row[10]), float(row[11])
                lm_x, lm_y = float(row[12]), float(row[13])

                bbox_cx = x + 0.5 * w
                eye_mid_x = 0.5 * (re_x + le_x)
                eye_mid_y = 0.5 * (re_y + le_y)
                # Blend landmarks with box center so 3/4 profile turns stay well framed
                cx_det = 0.50 * bbox_cx + 0.30 * nose_x + 0.20 * eye_mid_x
                cx_src = max(0.0, min(float(src_w), cx_det / scale_x))
                eye_y_src = max(0.0, min(float(src_h), eye_mid_y / scale_y))
                # Frame eyes near the upper third (~36% down) when vertical crop slack exists
                cy_src = max(0.0, min(float(src_h), eye_y_src + 0.14 * crop_h))

                mx1 = int(max(0, min(det_w - 1, min(rm_x, lm_x) - 0.18 * w)))
                mx2 = int(max(mx1 + 1, min(det_w, max(rm_x, lm_x) + 0.18 * w)))
                my1 = int(max(0, min(det_h - 1, min(rm_y, lm_y) - 0.12 * h)))
                my2 = int(max(my1 + 1, min(det_h, max(rm_y, lm_y) + 0.20 * h)))
                if mx2 - mx1 < 4 or my2 - my1 < 4:
                    mx1 = int(max(0, x + 0.15 * w))
                    mx2 = int(min(det_w, x + 0.85 * w))
                    my1 = int(max(0, y + 0.60 * h))
                    my2 = int(min(det_h, y + 0.98 * h))

                results.append({
                    "x": x / scale_x,
                    "y": y / scale_y,
                    "w": w / scale_x,
                    "h": h / scale_y,
                    "score": score,
                    "cx": cx_src,
                    "cy": cy_src,
                    "mouth_box": (mx1, my1, mx2, my2),
                })
        return results

    if detector_kind == "haar" and detector is not None:
        faces = detector.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(24, 24))
        for (x, y, w, h) in faces:
            cx_src = max(0.0, min(float(src_w), (x + 0.5 * w) / scale_x))
            eye_y_src = max(0.0, min(float(src_h), (y + 0.36 * h) / scale_y))
            cy_src = max(0.0, min(float(src_h), eye_y_src + 0.14 * crop_h))
            mx1 = int(max(0, x + 0.15 * w))
            mx2 = int(min(det_w, x + 0.85 * w))
            my1 = int(max(0, y + 0.60 * h))
            my2 = int(min(det_h, y + 0.98 * h))
            results.append({
                "x": x / scale_x,
                "y": y / scale_y,
                "w": w / scale_x,
                "h": h / scale_y,
                "score": 0.75,
                "cx": cx_src,
                "cy": cy_src,
                "mouth_box": (mx1, my1, mx2, my2),
            })
    return results


def _is_shot_cut(cv2_mod, np_mod, prev_small, prev_hist, curr_small) -> Tuple[bool, object]:
    """Detect camera cuts using grayscale histogram correlation and mean frame difference."""
    curr_hist = cv2_mod.calcHist([curr_small], [0], None, [32], [0, 256])
    cv2_mod.normalize(curr_hist, curr_hist, alpha=1.0, norm_type=cv2_mod.NORM_L1)
    if prev_small is None or prev_hist is None:
        return False, curr_hist
    corr = float(cv2_mod.compareHist(prev_hist, curr_hist, cv2_mod.HISTCMP_CORREL))
    mean_diff = float(np_mod.mean(cv2_mod.absdiff(prev_small, curr_small)))
    return (corr < 0.65 or mean_diff > 36.0), curr_hist


def _compute_saliency_center(
    cv2_mod, np_mod, small_gray, prev_small_gray, src_w: int, src_h: int
) -> Tuple[float, float]:
    """Compute a center-prioritized edge + motion visual saliency centroid in source space."""
    sh, sw = small_gray.shape[:2]
    gx = cv2_mod.Sobel(small_gray, cv2_mod.CV_32F, 1, 0, ksize=3)
    gy = cv2_mod.Sobel(small_gray, cv2_mod.CV_32F, 0, 1, ksize=3)
    grad = cv2_mod.magnitude(gx, gy)
    g_max = float(np_mod.max(grad))
    energy = (grad / g_max) if g_max > 1e-3 else np_mod.zeros_like(grad)

    if prev_small_gray is not None:
        diff = cv2_mod.absdiff(small_gray, prev_small_gray).astype(np_mod.float32)
        d_max = float(np_mod.max(diff))
        if d_max > 12.0:
            energy = 0.45 * energy + 0.55 * (diff / d_max)

    xs = np_mod.linspace(-1.0, 1.0, sw, dtype=np_mod.float32)
    ys = np_mod.linspace(-1.0, 1.0, sh, dtype=np_mod.float32)
    prior_x = np_mod.exp(-0.5 * (xs / 0.72) ** 2)
    prior_y = np_mod.exp(-0.5 * (ys / 0.72) ** 2)
    weight = energy * (prior_y[:, None] * prior_x[None, :])
    total = float(np_mod.sum(weight))
    if total < 1e-3:
        return src_w * 0.5, src_h * 0.5

    x_coords = np_mod.arange(sw, dtype=np_mod.float32) + 0.5
    y_coords = np_mod.arange(sh, dtype=np_mod.float32) + 0.5
    cx_small = float(np_mod.sum(weight * x_coords[None, :]) / total)
    cy_small = float(np_mod.sum(weight * y_coords[:, None]) / total)
    return (cx_small / sw) * src_w, (cy_small / sh) * src_h


def _iter_sampled_frames(
    cv2_mod,
    np_mod,
    in_path: str,
    start_time: float,
    end_time: float,
    det_w: int,
    det_h: int,
    sample_fps: float,
    fps: float,
) -> Iterator:
    """Decode sampled downscaled BGR frames via FFmpeg pipe, with cv2.VideoCapture fallback."""
    clip_dur = max(0.1, end_time - start_time)
    max_samples = max(2, int(math.ceil(clip_dur * sample_fps)) + 8)
    frame_bytes = det_w * det_h * 3
    yielded = 0

    if os.path.isfile(in_path):
        cmd = [
            "ffmpeg", "-v", "error",
            "-ss", f"{max(0.0, start_time):.3f}",
            "-t", f"{clip_dur:.3f}",
            "-i", in_path,
            "-vf", f"fps={sample_fps:.3f},scale={det_w}:{det_h}:flags=fast_bilinear",
            "-pix_fmt", "bgr24",
            "-f", "rawvideo",
            "pipe:1",
        ]
        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            assert proc.stdout is not None
            while yielded < max_samples:
                buf = bytearray()
                while len(buf) < frame_bytes:
                    chunk = proc.stdout.read(frame_bytes - len(buf))
                    if not chunk:
                        break
                    buf.extend(chunk)
                if len(buf) < frame_bytes:
                    break
                frame = np_mod.frombuffer(buf, dtype=np_mod.uint8).reshape((det_h, det_w, 3)).copy()
                yielded += 1
                yield frame
        except Exception:
            pass
        finally:
            if proc is not None:
                try:
                    if proc.stdout:
                        proc.stdout.close()
                except Exception:
                    pass
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

    if yielded > 0:
        return

    # Fallback to cv2.VideoCapture when FFmpeg pipe cannot decode (e.g. unit-test stubs)
    cap = cv2_mod.VideoCapture(in_path)
    if not cap.isOpened():
        return
    try:
        target_ms = max(0.0, start_time * 1000.0)
        cap.set(cv2_mod.CAP_PROP_POS_MSEC, target_ms)
        for _ in range(300):
            if cap.get(cv2_mod.CAP_PROP_POS_MSEC) >= target_ms:
                break
            if not cap.grab():
                break
        safe_fps = fps if fps and fps > 0 else 30.0
        step = max(1, int(round(safe_fps / max(0.5, sample_fps))))
        total_frames = int(max(1.0, clip_dur * safe_fps))
        fidx = 0
        while fidx < total_frames and yielded < max_samples:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            if fidx % step == 0:
                if frame.shape[1] != det_w or frame.shape[0] != det_h:
                    frame = cv2_mod.resize(frame, (det_w, det_h), interpolation=cv2_mod.INTER_LINEAR)
                yielded += 1
                yield frame
            fidx += 1
    finally:
        cap.release()


def _resolve_shot_targets(
    shot_samples: List[Dict], src_w: int, src_h: int, sample_fps: float
) -> List[Tuple[float, float]]:
    """Select active target (cx, cy) per sample within a single shot with speaker hysteresis."""
    if not shot_samples:
        return []
    default_center = (src_w * 0.5, src_h * 0.5)
    hold_limit = max(2, int(round(1.5 * sample_fps)))
    lock_dist = 0.18 * src_w

    locked_center: Optional[Tuple[float, float]] = None
    challenger_center: Optional[Tuple[float, float]] = None
    challenger_streak = 0
    miss_streak = 0
    raw_targets: List[Optional[Tuple[float, float]]] = []
    first_face_target: Optional[Tuple[float, float]] = None

    for sample in shot_samples:
        faces = sample["faces"]
        saliency = sample["saliency"]

        if faces:
            max_area = max(max(1.0, f["w"] * f["h"]) for f in faces)
            scored = []
            for f in faces:
                area_norm = max(1.0, f["w"] * f["h"]) / max_area
                center_bias = 1.0 - 0.15 * min(1.0, abs(f["cx"] - src_w * 0.5) / max(1.0, src_w * 0.5))
                mouth_motion = min(1.5, max(0.0, float(f.get("mouth_motion", 0.0))))
                rank_score = float(f["score"]) * (0.55 + 0.45 * area_norm) * center_bias * (1.0 + 0.55 * mouth_motion)
                scored.append((rank_score, f))
            scored.sort(key=lambda item: item[0], reverse=True)

            chosen = None
            if locked_center is not None:
                locked_pair = None
                best_dist = lock_dist
                for sc, f in scored:
                    d = math.hypot(f["cx"] - locked_center[0], f["cy"] - locked_center[1])
                    if d < best_dist:
                        best_dist = d
                        locked_pair = (sc, f)

                if locked_pair is not None:
                    locked_sc, locked_f = locked_pair
                    other = next(((sc, f) for sc, f in scored if f is not locked_f), None)
                    if other is not None and other[0] > locked_sc * 1.35:
                        oth_f = other[1]
                        if challenger_center is not None and math.hypot(
                            oth_f["cx"] - challenger_center[0], oth_f["cy"] - challenger_center[1]
                        ) < lock_dist:
                            challenger_streak += 1
                        else:
                            challenger_center = (oth_f["cx"], oth_f["cy"])
                            challenger_streak = 1
                        if challenger_streak >= 3:
                            chosen = oth_f
                            challenger_center = None
                            challenger_streak = 0
                        else:
                            chosen = locked_f
                    else:
                        chosen = locked_f
                        challenger_center = None
                        challenger_streak = 0
                else:
                    # Locked face briefly missing: require 2 consecutive misses (~0.33s) before switching to a faraway face
                    top_sc, top_f = scored[0]
                    if miss_streak >= 2:
                        chosen = top_f
                        challenger_center = None
                        challenger_streak = 0
            else:
                chosen = scored[0][1]

            if chosen is not None:
                miss_streak = 0
                locked_center = (chosen["cx"], chosen["cy"])
                if first_face_target is None:
                    first_face_target = locked_center
                raw_targets.append(locked_center)
                continue

        # No face selected on this sample
        miss_streak += 1
        challenger_center = None
        challenger_streak = 0
        if locked_center is not None and miss_streak <= hold_limit:
            raw_targets.append(locked_center)
        else:
            raw_targets.append(None if first_face_target is None else saliency)

    # Backfill leading samples in a shot where a face appears shortly after the cut
    resolved: List[Tuple[float, float]] = []
    for idx, t in enumerate(raw_targets):
        if t is not None:
            resolved.append(t)
        elif first_face_target is not None:
            resolved.append(first_face_target)
        else:
            resolved.append(shot_samples[idx].get("saliency") or default_center)
    return resolved


def _smooth_shot_trajectory(
    targets: List[Tuple[float, float]], crop_w: int, crop_h: int, sample_fps: float
) -> List[Tuple[float, float]]:
    """Stabilize a single shot's trajectory with median filtering, deadzone, and velocity-clamped EMA."""
    n = len(targets)
    if n <= 1:
        return list(targets)

    # 3-sample median filter removes single-frame false detections without adding drift
    med: List[Tuple[float, float]] = []
    for i in range(n):
        lo = max(0, i - 1)
        hi = min(n, i + 2)
        xs = sorted(targets[j][0] for j in range(lo, hi))
        ys = sorted(targets[j][1] for j in range(lo, hi))
        med.append((xs[len(xs) // 2], ys[len(ys) // 2]))

    deadzone_x = 0.06 * crop_w
    deadzone_y = 0.06 * crop_h
    max_step_x = max(2.0, (0.65 * crop_w) / max(1.0, sample_fps))
    max_step_y = max(2.0, (0.65 * crop_h) / max(1.0, sample_fps))
    alpha = 0.34

    cam_x, cam_y = med[0]
    smoothed: List[Tuple[float, float]] = [(cam_x, cam_y)]
    for i in range(1, n):
        tx, ty = med[i]
        dx = tx - cam_x
        if abs(dx) > deadzone_x:
            eff_dx = dx - math.copysign(deadzone_x, dx)
            step_x = max(-max_step_x, min(max_step_x, alpha * eff_dx))
            cam_x += step_x

        dy = ty - cam_y
        if abs(dy) > deadzone_y:
            eff_dy = dy - math.copysign(deadzone_y, dy)
            step_y = max(-max_step_y, min(max_step_y, alpha * eff_dy))
            cam_y += step_y

        smoothed.append((cam_x, cam_y))
    return smoothed


def _expand_shots_to_frame_origins(
    shots: List[List[Tuple[int, Tuple[float, float]]]],
    src_w: int,
    src_h: int,
    crop_w: int,
    crop_h: int,
    total_frames: int,
    sample_fps: float,
    fps: float,
) -> List[Tuple[int, int]]:
    """Expand per-shot smoothed samples to per-frame crop origins, snapping cleanly on shot cuts."""
    max_x0 = max(0, src_w - crop_w)
    max_y0 = max(0, src_h - crop_h)
    safe_fps = fps if fps and fps > 0 else 30.0
    frame_scale = safe_fps / max(0.5, sample_fps)

    def to_origin(pt: Tuple[float, float]) -> Tuple[int, int]:
        x0 = max(0, min(max_x0, int(round(pt[0] - crop_w * 0.5))))
        y0 = max(0, min(max_y0, int(round(pt[1] - crop_h * 0.5))))
        return (x0, y0)

    if not shots:
        return [(max_x0 // 2, max_y0 // 2)] * max(1, total_frames)

    # Map each shot to its [start_frame, end_frame) span so cuts snap instantaneously
    shot_spans: List[Tuple[int, int, List[Tuple[int, Tuple[float, float]]]]] = []
    for idx, shot in enumerate(shots):
        if not shot:
            continue
        start_f = 0 if idx == 0 else int(round(shot[0][0] * frame_scale))
        shot_spans.append((start_f, total_frames, shot))

    for idx in range(len(shot_spans) - 1):
        sf, _, shot = shot_spans[idx]
        next_sf, next_ef, next_shot = shot_spans[idx + 1]
        boundary = max(sf + 1, next_sf)
        shot_spans[idx] = (sf, boundary, shot)
        shot_spans[idx + 1] = (boundary, next_ef, next_shot)

    origins: List[Tuple[int, int]] = []
    for sf, ef, shot in shot_spans:
        if sf >= total_frames:
            break
        ef = min(total_frames, ef)
        sample_frames = [int(round(s_idx * frame_scale)) for s_idx, _ in shot]
        sample_pts = [pt for _, pt in shot]
        for f in range(sf, ef):
            if f <= sample_frames[0]:
                pt = sample_pts[0]
            elif f >= sample_frames[-1]:
                pt = sample_pts[-1]
            else:
                pt = sample_pts[-1]
                for j in range(len(sample_frames) - 1):
                    a, b = sample_frames[j], sample_frames[j + 1]
                    if a <= f <= b:
                        t = (f - a) / float(b - a) if b != a else 0.0
                        ax, ay = sample_pts[j]
                        bx, by = sample_pts[j + 1]
                        pt = (ax + (bx - ax) * t, ay + (by - ay) * t)
                        break
            origins.append(to_origin(pt))

    if not origins:
        origins.append((max_x0 // 2, max_y0 // 2))
    while len(origins) < max(1, total_frames):
        origins.append(origins[-1])
    return origins[: max(1, total_frames)]


def _sample_face_centers(
    in_path: str, src_w: int, src_h: int, crop_w: int, crop_h: int, start_time: float, end_time: float, fps: float
) -> List[Tuple[int, int]]:
    """Track active speaker/subject across shots using YuNet + saliency + deadzone smoothing."""
    static_origin = (
        max(0, (src_w - crop_w) // 2),
        max(0, (src_h - crop_h) // 2),
    )
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception as e:
        print(f"[clip/local] face detect unavailable ({e}), using static center crop", flush=True)
        return [static_origin]

    det_w = min(480, max(160, src_w - (src_w % 2)))
    det_h = max(90, int(round(src_h * (det_w / float(max(1, src_w))))))
    det_h = max(2, det_h - (det_h % 2))

    detector_kind, detector = _create_face_detector(cv2, det_w, det_h)
    if detector_kind is None:
        print("[clip/local] no face detector available, using static center crop", flush=True)
        return [static_origin]

    sample_fps = FACE_TRACK_SAMPLE_FPS
    safe_fps = fps if fps and fps > 0 else 30.0
    total_frames = int(max(1.0, round((end_time - start_time) * safe_fps)))

    raw_shots: List[List[Tuple[int, Dict]]] = []
    current_shot: List[Tuple[int, Dict]] = []
    prev_gray = None
    prev_small = None
    prev_hist = None

    for s_idx, frame in enumerate(
        _iter_sampled_frames(cv2, np, in_path, start_time, end_time, det_w, det_h, sample_fps, safe_fps)
    ):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
        is_cut, curr_hist = _is_shot_cut(cv2, np, prev_small, prev_hist, small)
        if is_cut and current_shot:
            raw_shots.append(current_shot)
            current_shot = []
            prev_gray = None
            prev_small = None

        faces = _detect_faces_in_frame(
            cv2, detector_kind, detector, frame, gray, det_w, det_h, src_w, src_h, crop_h
        )
        if faces and prev_gray is not None:
            for f in faces:
                mx1, my1, mx2, my2 = f["mouth_box"]
                if mx2 > mx1 and my2 > my1:
                    roi_diff = cv2.absdiff(gray[my1:my2, mx1:mx2], prev_gray[my1:my2, mx1:mx2])
                    f["mouth_motion"] = float(np.mean(roi_diff)) / 25.0
                else:
                    f["mouth_motion"] = 0.0

        saliency = _compute_saliency_center(cv2, np, small, prev_small, src_w, src_h)
        current_shot.append((s_idx, {"faces": faces, "saliency": saliency}))
        prev_gray = gray
        prev_small = small
        prev_hist = curr_hist

    if current_shot:
        raw_shots.append(current_shot)

    if not raw_shots:
        return [static_origin]

    smoothed_shots: List[List[Tuple[int, Tuple[float, float]]]] = []
    for shot in raw_shots:
        s_indices = [idx for idx, _ in shot]
        s_data = [data for _, data in shot]
        targets = _resolve_shot_targets(s_data, src_w, src_h, sample_fps)
        smoothed = _smooth_shot_trajectory(targets, crop_w, crop_h, sample_fps)
        smoothed_shots.append(list(zip(s_indices, smoothed)))

    return _expand_shots_to_frame_origins(
        smoothed_shots, src_w, src_h, crop_w, crop_h, total_frames, sample_fps, safe_fps
    )


_DETECTED_ENCODER_FLAGS: Optional[List[str]] = None
_ENCODER_LOCK = threading.Lock()


def _downgrade_to_software_encoder() -> List[str]:
    """Permanently switch cached encoder to libx264 after a hardware hang/failure."""
    global _DETECTED_ENCODER_FLAGS
    with _ENCODER_LOCK:
        _DETECTED_ENCODER_FLAGS = list(_SOFTWARE_ENCODER_FLAGS)
        return _DETECTED_ENCODER_FLAGS


def _get_encoder_flags() -> List[str]:
    global _DETECTED_ENCODER_FLAGS
    with _ENCODER_LOCK:
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
                with _ENCODER_LOCK:
                    _DETECTED_ENCODER_FLAGS = list(flags)
                    return _DETECTED_ENCODER_FLAGS
        except Exception:
            pass

    with _ENCODER_LOCK:
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
    clip_timeout = max(75.0, clip_dur * 2.0 + 30.0)
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
            "-avoid_negative_ts", "make_zero",
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
        # Hardware drivers (e.g. h264_amf / h264_mf) can hang or fail mid-stream; discard partial MP4,
        # downgrade the cached encoder so later clips do not repeat the stall, and fall back cleanly.
        print(f"[clip/local] hardware encode failed ({exc}), switching to libx264", flush=True)
        _downgrade_to_software_encoder()
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
        unique_positions = set(centers)
        if len(unique_positions) <= 1:
            x0, y0 = centers[0]
            _encode(
                source_path, start_time, padded_end, f"crop={crop_w}:{crop_h}:{x0}:{y0}", enc_flags, out_path, cues,
                crop_w, crop_h, worker_threads=worker_threads, cancel_event=cancel_event,
            )
            return out_path

        sendcmd_path = out_path + ".sendcmd.txt"
        with open(sendcmd_path, "w", encoding="utf-8") as f:
            last_xy: Optional[Tuple[int, int]] = None
            for i, (x0, y0) in enumerate(centers):
                if last_xy is not None and (x0, y0) == last_xy:
                    continue
                t = i / fps if fps else 0.0
                f.write(f"{t:.5f} [enter] crop@c x {x0}, [enter] crop@c y {y0};\n")
                last_xy = (x0, y0)

        crop_filter = f"crop@c={crop_w}:{crop_h}:{centers[0][0]}:{centers[0][1]}"
        escaped_path = _escape_filter_path(sendcmd_path)
        if "\n" in escaped_path or "\r" in escaped_path:
            # a path we cannot express inside a filtergraph must not kill the clip
            print("[clip/local] sendcmd path is not filter-safe, using static center crop", flush=True)
            if os.path.exists(sendcmd_path):
                os.remove(sendcmd_path)
        else:
            # sendcmd MUST precede crop@c so updated x/y applies to the current frame before cropping
            vf = f"sendcmd=f={escaped_path},{crop_filter}"
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
    # AMD AMF and Windows MediaFoundation hardware sessions can deadlock under concurrent encodes,
    # whereas NVENC/QSV support 2 concurrent encodes and software libx264 scales up to 3 parallel workers.
    if _is_serial_hardware_encoder(enc_flags):
        max_workers = 1
        worker_threads = 0
    elif _is_hardware_encoder(enc_flags):
        max_workers = 2
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