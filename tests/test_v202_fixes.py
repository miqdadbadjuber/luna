import json
import os
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

import luna.app as app_module
from luna import studio_service
from luna.clipper import clipper, transcriber

STUDIO_JS_PATH = Path(__file__).resolve().parent.parent / "luna" / "assets" / "ui" / "studio.js"


def _extract_js_function(source: str, func_name: str) -> str:
    marker = f"function {func_name}("
    start = source.index(marker)
    brace_start = source.index("{", start)
    depth = 0
    for idx in range(brace_start, len(source)):
        ch = source[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start : idx + 1]
    raise RuntimeError(f"Could not find end of JS function {func_name}")


class TestStudioUrlAndPreviewSync(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is required for JS helper tests")
    def test_encode_media_url_does_not_double_encode_semicolon_or_emoji(self):
        js_src = STUDIO_JS_PATH.read_text(encoding="utf-8")
        fn_code = _extract_js_function(js_src, "encodeMediaUrl")
        script = f"""
{fn_code}
const cases = [
  "/media-vault/02-Full-Video/%F0%9F%94%B4%20FMS%20BY%20NIVEA%20MEN%3A%20IN-DEPTH%3B%20BAYERN%20VS%20MUSIALA.mp4",
  "/media-vault/02-Full-Video/My Video; #1 & 100%.mp4",
  "/api/studio/proj_1/filmstrip/clip_1?v=123",
  "javascript:alert(1)"
];
console.log(JSON.stringify(cases.map(encodeMediaUrl)));
"""
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        out = json.loads(res.stdout)
        self.assertNotIn("%253B", out[0])
        self.assertNotIn("%253A", out[0])
        self.assertIn("%3B", out[0])
        self.assertIn("%F0%9F%94%B4", out[0])
        self.assertIn("%3B", out[1])
        self.assertIn("%23", out[1])
        self.assertIn("%25", out[1])
        self.assertTrue(out[2].endswith("?v=123"))
        self.assertEqual(out[3], "#")

    @unittest.skipUnless(shutil.which("node"), "node is required for JS helper tests")
    def test_studio_current_display_cue_hides_in_playback_gaps(self):
        js_src = STUDIO_JS_PATH.read_text(encoding="utf-8")
        fn_code = _extract_js_function(js_src, "currentDisplayCue")
        script = f"""
const cues = [
  {{ start: 1.2, end: 2.8, text: "First spoken line" }},
  {{ start: 4.0, end: 5.5, text: "Second spoken line" }}
];
const state = {{ currentTime: 0, playing: true }};
function activeClip() {{ return {{ cues }}; }}
{fn_code}
const playingBefore = currentDisplayCue(0.4);
const playingInside = currentDisplayCue(1.6);
const playingGap = currentDisplayCue(3.3);
state.playing = false;
const pausedBefore = currentDisplayCue(0.4);
console.log(JSON.stringify({{ playingBefore, playingInside, playingGap, pausedBefore }}));
"""
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        out = json.loads(res.stdout)
        self.assertIsNone(out["playingBefore"])
        self.assertEqual(out["playingInside"]["text"], "First spoken line")
        self.assertIsNone(out["playingGap"])
        self.assertEqual(out["pausedBefore"]["text"], "First spoken line")
        self.assertEqual(out["pausedBefore"]["start"], 1.2)

    @unittest.skipUnless(shutil.which("node"), "node is required for JS helper tests")
    def test_studio_serves_video_with_semicolon_and_emoji_filename(self):
        js_src = STUDIO_JS_PATH.read_text(encoding="utf-8")
        fn_code = _extract_js_function(js_src, "encodeMediaUrl")
        with tempfile.TemporaryDirectory() as tmp:
            proj_dir = Path(tmp) / "02-Full-Video" / "Match Review"
            proj_dir.mkdir(parents=True)
            fname = "🔴 IN-DEPTH; BAYERN VS MUSIALA.mp4"
            media_file = proj_dir / fname
            media_file.write_bytes(b"fake-mp4-bytes")

            with patch.object(studio_service.storage_manager, "get_storage_root", return_value=tmp), \
                    patch.object(app_module, "get_storage_root", return_value=tmp):
                raw_url = studio_service._media_vault_url(str(media_file))
                res = subprocess.run(
                    ["node", "-e", f"{fn_code}\nconsole.log(encodeMediaUrl({json.dumps(raw_url)}));"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                encoded_url = res.stdout.strip()
                self.assertNotIn("%253B", encoded_url)
                client = TestClient(app_module.app)
                resp = client.get(encoded_url)

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.content, b"fake-mp4-bytes")


class TestGroqSubtitleSync(unittest.TestCase):
    def test_groq_requests_word_timestamps_and_tightens_segment_silence(self):
        seen_kwargs = {}

        class _FakeResp:
            duration = 6.0
            segments = [
                {"start": 0.0, "end": 3.5, "text": "Halo semua selamat datang"},
                {"start": 3.5, "end": 6.0, "text": "kita mulai sekarang"},
            ]
            words = [
                {"word": "Halo", "start": 0.90, "end": 1.15},
                {"word": "semua", "start": 1.18, "end": 1.55},
                {"word": "selamat", "start": 1.60, "end": 2.05},
                {"word": "datang", "start": 2.10, "end": 2.55},
                {"word": "kita", "start": 4.10, "end": 4.35},
                {"word": "mulai", "start": 4.40, "end": 4.75},
                {"word": "sekarang", "start": 4.80, "end": 5.30},
            ]

        class _FakeTranscriptions:
            def create(self, **kwargs):
                seen_kwargs.update(kwargs)
                return _FakeResp()

        class _FakeOpenAI:
            def __init__(self, **kwargs):
                self.audio = types.SimpleNamespace(transcriptions=_FakeTranscriptions())

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = _FakeOpenAI

        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict("sys.modules", {"openai": fake_openai}), \
                patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_key"}), \
                patch.object(transcriber, "_extract_compressed_audio", lambda _src, out: Path(out).write_bytes(b"ogg")):
            result = transcriber._transcribe_local_groq(os.path.join(tmp, "video.mp4"), language="id")

        self.assertEqual(seen_kwargs.get("timestamp_granularities"), ["word", "segment"])
        self.assertEqual(len(result["words"]), 7)
        # Leading/trailing silence padding trimmed tightly to actual spoken words
        self.assertAlmostEqual(result["segments"][0]["start"], 0.90, places=2)
        self.assertAlmostEqual(result["segments"][0]["end"], 2.55, places=2)
        self.assertAlmostEqual(result["segments"][1]["start"], 4.10, places=2)
        self.assertAlmostEqual(result["segments"][1]["end"], 5.30, places=2)

    def test_words_sidecar_cache_and_studio_word_cues_and_ass_timing(self):
        words = [
            {"start": 10.50, "end": 10.80, "text": "Ini"},
            {"start": 10.85, "end": 11.20, "text": "adalah"},
            {"start": 11.25, "end": 11.65, "text": "contoh"},
            {"start": 11.70, "end": 12.10, "text": "kalimat"},
            {"start": 12.15, "end": 12.60, "text": "pertama."},
            {"start": 13.40, "end": 13.70, "text": "Lalu"},
            {"start": 13.75, "end": 14.15, "text": "lanjut"},
            {"start": 14.20, "end": 14.60, "text": "lagi."},
        ]
        transcript = {
            "duration": 15.0,
            "segments": [{"start": 10.50, "end": 14.60, "text": "Ini adalah contoh kalimat pertama. Lalu lanjut lagi."}],
            "words": words,
        }
        with tempfile.TemporaryDirectory() as tmp:
            media_path = os.path.join(tmp, "source_vid.mp4")
            Path(media_path).write_bytes(b"x")
            with patch.object(transcriber, "local_output_dir", return_value=tmp):
                srt_path = transcriber._write_srt_cache(media_path, transcript, provider="groq", language="id")
                loaded = transcriber._load_srt_cache(srt_path)
            self.assertEqual(len(loaded.get("words") or []), len(words))

        cues = studio_service._build_word_synced_cues(words, clip_start=10.0, clip_end=15.0)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[0]["start"], 0.50, places=2)
        self.assertAlmostEqual(cues[0]["end"], 2.60, places=2)
        self.assertIn("splitTime", cues[0])
        self.assertGreater(cues[0]["splitTime"], cues[0]["start"])
        self.assertLess(cues[0]["splitTime"], cues[0]["end"])
        self.assertAlmostEqual(cues[1]["start"], 3.40, places=2)

        # ASS builder must NOT force cue #1 start back to 0:00:00.00 when skipping a tiny stub
        cues_with_stub = [{"start": 0.0, "end": 0.12, "text": "uh"}] + cues
        ass_text = studio_service._build_selene_ass(
            cues_with_stub, trim_start=0.0, trim_end=5.0, width=1080, height=1920,
            size_scale=1.0, pos_x_pct=50.0, pos_y_pct=78.0,
        )
        dialogue_lines = [ln for ln in ass_text.splitlines() if ln.startswith("Dialogue:")]
        self.assertGreaterEqual(len(dialogue_lines), 2)
        self.assertIn("0:00:00.50", dialogue_lines[0])
        self.assertNotIn("0:00:00.00", dialogue_lines[0])
        # Exact splitTime transition used for Line 1 -> Line 2 emphasis
        expected_split_ts = studio_service._ass_timestamp(cues[0]["splitTime"])
        self.assertIn(expected_split_ts, dialogue_lines[0])
        self.assertIn(expected_split_ts, dialogue_lines[1])


class TestFaceTrackingUpgrade(unittest.TestCase):
    def test_yunet_model_is_bundled_and_loads(self):
        import cv2  # type: ignore

        self.assertTrue(os.path.isfile(clipper._YUNET_MODEL_PATH))
        kind, det = clipper._create_face_detector(cv2, 320, 180)
        self.assertEqual(kind, "yunet")
        self.assertIsNotNone(det)

    def test_deadzone_stabilizes_small_jitter_and_tracks_large_move(self):
        # Small micro-jitter within +-6% of 608px (~36px) must keep camera completely steady
        jitter = [(960.0 + (12.0 if i % 2 else -12.0), 540.0) for i in range(12)]
        smoothed_jitter = clipper._smooth_shot_trajectory(jitter, crop_w=608, crop_h=1080, sample_fps=6.0)
        xs = [pt[0] for pt in smoothed_jitter]
        self.assertLessEqual(max(xs) - min(xs), 1e-6)

        # Large walk across frame must pan smoothly without jumping in a single step
        walk = [(400.0, 540.0)] * 3 + [(1400.0, 540.0)] * 15
        smoothed_walk = clipper._smooth_shot_trajectory(walk, crop_w=608, crop_h=1080, sample_fps=6.0)
        self.assertAlmostEqual(smoothed_walk[0][0], 400.0, places=1)
        self.assertGreater(smoothed_walk[-1][0], 1100.0)
        max_step = max(abs(smoothed_walk[i][0] - smoothed_walk[i - 1][0]) for i in range(1, len(smoothed_walk)))
        self.assertLessEqual(max_step, (0.65 * 608) / 6.0 + 1.0)

    def test_active_speaker_hysteresis_and_shot_cut_instant_snap(self):
        left_face = {"x": 360, "y": 200, "w": 160, "h": 160, "score": 0.90, "cx": 440.0, "cy": 540.0, "mouth_motion": 0.10}
        right_quiet = {"x": 1400, "y": 200, "w": 160, "h": 160, "score": 0.90, "cx": 1480.0, "cy": 540.0, "mouth_motion": 0.05}
        right_talking = {"x": 1400, "y": 200, "w": 160, "h": 160, "score": 0.95, "cx": 1480.0, "cy": 540.0, "mouth_motion": 1.20}

        # Single noisy spike on right speaker must NOT switch camera; 3+ sustained talking frames DO switch
        shot = [
            {"faces": [left_face, right_quiet], "saliency": (960.0, 540.0)},
            {"faces": [left_face, right_talking], "saliency": (960.0, 540.0)},  # streak 1
            {"faces": [left_face, right_quiet], "saliency": (960.0, 540.0)},    # reset
            {"faces": [left_face, right_talking], "saliency": (960.0, 540.0)},  # streak 1
            {"faces": [left_face, right_talking], "saliency": (960.0, 540.0)},  # streak 2
            {"faces": [left_face, right_talking], "saliency": (960.0, 540.0)},  # streak 3 -> switch!
        ]
        targets = clipper._resolve_shot_targets(shot, src_w=1920, src_h=1080, sample_fps=6.0)
        self.assertAlmostEqual(targets[1][0], 440.0, places=1)
        self.assertAlmostEqual(targets[4][0], 440.0, places=1)
        self.assertAlmostEqual(targets[5][0], 1480.0, places=1)

        # Shot cut snaps immediately without blending across shots
        shots = [
            [(0, (304.0, 540.0)), (1, (304.0, 540.0)), (2, (304.0, 540.0))],
            [(3, (1616.0, 540.0)), (4, (1616.0, 540.0)), (5, (1616.0, 540.0))],
        ]
        origins = clipper._expand_shots_to_frame_origins(
            shots, src_w=1920, src_h=1080, crop_w=608, crop_h=1080, total_frames=30, sample_fps=6.0, fps=30.0
        )
        # Frame 14 (just before cut at sample 3 -> frame 15) stays at x0=0; frame 15 snaps straight to x0=1312
        self.assertEqual(origins[14][0], 0)
        self.assertEqual(origins[15][0], 1312)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for live sendcmd crop verification")
    def test_sendcmd_precedes_crop_and_moves_crop_window_dynamically(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "split.mp4")
            # Left half (x < 320) is pure RED, right half (x >= 320) is pure GREEN
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=red:s=320x360:r=10:d=2",
                    "-f", "lavfi", "-i", "color=c=green:s=320x360:r=10:d=2",
                    "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]",
                    "-map", "[v]", "-pix_fmt", "yuv420p", source,
                ],
                check=True,
            )
            out = os.path.join(tmp, "tracked.mp4")
            # Force crop to start on left red half (x=0) for t < 1.0s and jump to right green half (x=438) at t >= 1.0s
            fake_centers = [(0, 0)] * 10 + [(438, 0)] * 10
            with patch.object(clipper, "_sample_face_centers", return_value=fake_centers), \
                    patch.object(clipper, "_get_encoder_flags", return_value=list(clipper._SOFTWARE_ENCODER_FLAGS)):
                clipper.crop_clip_local(source, 0.0, 2.0, "9:16", out, use_face_detect=True)

            f_early = os.path.join(tmp, "early.png")
            f_late = os.path.join(tmp, "late.png")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.3", "-i", out, "-frames:v", "1", f_early], check=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5", "-i", out, "-frames:v", "1", f_late], check=True)

            im_early = Image.open(f_early).convert("RGB")
            im_late = Image.open(f_late).convert("RGB")
            r1, g1, _ = im_early.getpixel((im_early.width // 2, im_early.height // 2))
            r2, g2, _ = im_late.getpixel((im_late.width // 2, im_late.height // 2))

            self.assertGreater(r1, 180)
            self.assertLess(g1, 60)
            self.assertGreater(g2, 100)
            self.assertLess(r2, 60)


if __name__ == "__main__":
    unittest.main()
