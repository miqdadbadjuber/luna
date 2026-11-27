import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import luna.app as app_module


class TestVideoFpsHandling(unittest.TestCase):
    def setUp(self):
        app_module._FPS_CHECK_CACHE.clear()

    def test_youtube_format_selector_respects_fps_target(self):
        sel_60 = app_module._youtube_video_format_selector("1080", "60")
        self.assertIn("bestvideo[height<=1080][fps>=50]", sel_60)
        self.assertIn("bestvideo[height<=1080]+bestaudio", sel_60)

        sel_30 = app_module._youtube_video_format_selector("720", "30")
        self.assertIn("bestvideo[height<=720][fps<=32]", sel_30)
        self.assertIn("bestvideo[height<=720]+bestaudio", sel_30)

        sel_auto = app_module._youtube_video_format_selector("1080", "auto")
        self.assertNotIn("[fps>=", sel_auto)
        self.assertNotIn("[fps<=", sel_auto)

    def test_parse_ffprobe_rate(self):
        self.assertAlmostEqual(app_module._parse_ffprobe_rate("60/1"), 60.0)
        self.assertAlmostEqual(app_module._parse_ffprobe_rate("60000/1001"), 59.94, places=2)
        self.assertAlmostEqual(app_module._parse_ffprobe_rate("30000/1001"), 29.97, places=2)
        self.assertIsNone(app_module._parse_ffprobe_rate("0/0"))
        self.assertIsNone(app_module._parse_ffprobe_rate("N/A"))
        self.assertIsNone(app_module._parse_ffprobe_rate(""))

    def test_evaluate_reencode_skips_redundant_and_fake_upsample(self):
        # Native 60fps downloaded with original ratio -> skip re-encode completely
        with patch.object(app_module, "_probe_source_fps", return_value=59.94), \
                patch.object(app_module, "_run_ffmpeg") as mock_ffmpeg:
            needs, src_fps, eff_fps = app_module._evaluate_video_reencode("in.mp4", "original", "60")
            self.assertFalse(needs)
            self.assertAlmostEqual(src_fps, 59.94)
            self.assertIsNone(eff_fps)
            out = app_module.format_video_target("in.mp4", ratio="original", fps="60")
            self.assertEqual(out, "in.mp4")
            mock_ffmpeg.assert_not_called()

        # 30fps source with target 60fps & original ratio -> do NOT fake-duplicate frames
        with patch.object(app_module, "_probe_source_fps", return_value=30.0):
            needs, src_fps, eff_fps = app_module._evaluate_video_reencode("in.mp4", "original", "60")
            self.assertFalse(needs)
            self.assertEqual(src_fps, 30.0)
            self.assertIsNone(eff_fps)

        # 30fps source with target 30fps -> already 30fps, skip re-encode
        with patch.object(app_module, "_probe_source_fps", return_value=29.97):
            needs, _, eff_fps = app_module._evaluate_video_reencode("in.mp4", "original", "30")
            self.assertFalse(needs)
            self.assertIsNone(eff_fps)

        # 60fps source with target 30fps -> genuinely needs downsample re-encode
        with patch.object(app_module, "_probe_source_fps", return_value=60.0):
            needs, _, eff_fps = app_module._evaluate_video_reencode("in.mp4", "original", "30")
            self.assertTrue(needs)
            self.assertEqual(eff_fps, "30")

        # Ratio change 9:16 on 30fps source -> re-encodes for crop without duplicating frames to 60fps
        with patch.object(app_module, "_probe_source_fps", return_value=30.0):
            needs, _, eff_fps = app_module._evaluate_video_reencode("in.mp4", "9:16", "60")
            self.assertTrue(needs)
            self.assertIsNone(eff_fps)

    def test_analyze_youtube_formats_fps_tristate_anti_false_negative(self):
        # 2:1 ultrawide 60fps video (e.g. 1920x960 @ 60fps, 1280x640 @ 60fps)
        ultrawide_60 = [
            {"vcodec": "avc1", "width": 854, "height": 428, "fps": 30},
            {"vcodec": "avc1", "width": 1280, "height": 640, "fps": 60},
            {"vcodec": "avc1", "width": 1920, "height": 960, "fps": 60},
            {"vcodec": "none", "acodec": "mp4a", "height": None, "fps": None},
        ]
        res_uw = app_module._analyze_youtube_formats_fps(ultrawide_60)
        self.assertTrue(res_uw["has_60fps"])
        self.assertEqual(res_uw["max_fps"], 60)
        self.assertEqual(res_uw["fps_60_heights"], [640, 960])

        # Vertical 9:16 Shorts 60fps (width=1080, height=1920 -> effective tier 1080)
        vert_60 = [
            {"vcodec": "vp9", "width": 1080, "height": 1920, "fps": 60},
        ]
        res_v = app_module._analyze_youtube_formats_fps(vert_60)
        self.assertTrue(res_v["has_60fps"])
        self.assertEqual(res_v["fps_60_heights"], [1080])

        # Genuine 30fps-only video with full DASH HD formats -> definitive False
        only_30 = [
            {"vcodec": "avc1", "width": 640, "height": 360, "fps": 30},
            {"vcodec": "avc1", "width": 854, "height": 480, "fps": 30},
            {"vcodec": "avc1", "width": 1280, "height": 720, "fps": 30},
            {"vcodec": "avc1", "width": 1920, "height": 1080, "fps": 29.97},
        ]
        res_30 = app_module._analyze_youtube_formats_fps(only_30)
        self.assertFalse(res_30["has_60fps"])
        self.assertEqual(res_30["max_fps"], 30)
        self.assertEqual(res_30["fps_60_heights"], [])

        # Throttled single 360p fallback stream -> must fail-open (None), NEVER false-lock!
        throttled = [{"vcodec": "avc1", "width": 640, "height": 360, "fps": 30}]
        res_th = app_module._analyze_youtube_formats_fps(throttled)
        self.assertIsNone(res_th["has_60fps"])

        # Empty formats -> fail-open (None)
        self.assertIsNone(app_module._analyze_youtube_formats_fps([])["has_60fps"])

    def test_check_fps_api_endpoint_and_cache(self):
        client = TestClient(app_module.app, base_url="http://127.0.0.1:8000")
        payload = {"has_60fps": False, "max_fps": 30, "fps_60_heights": []}
        with patch.object(app_module, "_probe_youtube_fps_sync", return_value=payload) as mock_probe:
            r1 = client.get("/api/check-fps", params={"url": "https://youtu.be/dQw4w9WgXcQ"})
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r1.json(), payload)
            # Second call hits in-memory cache
            r2 = client.get("/api/check-fps", params={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.json(), payload)
            self.assertEqual(mock_probe.call_count, 1)

        # Non-YouTube URL returns fail-open null without calling yt-dlp
        r_tt = client.get("/api/check-fps", params={"url": "https://www.tiktok.com/@user/video/123456"})
        self.assertEqual(r_tt.status_code, 200)
        self.assertIsNone(r_tt.json()["has_60fps"])


if __name__ == "__main__":
    unittest.main()
