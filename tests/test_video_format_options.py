import unittest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from luna.app import (
    ProcessRequest,
    _enforce_youtube_short_policy,
    extract_clip_segment,
    format_video_target,
    is_youtube_short_url,
    parse_timestamp,
)


class TestVideoFormatOptions(unittest.TestCase):
    def test_parse_timestamp_hours_and_minutes(self):
        self.assertEqual(parse_timestamp("00:30"), 30.0)
        self.assertEqual(parse_timestamp("03:20"), 200.0)
        self.assertEqual(parse_timestamp("01:15:30"), 4530.0)
        self.assertEqual(parse_timestamp("02:00:00"), 7200.0)
    def test_process_request_model_defaults(self):
        req = ProcessRequest(
            url="https://youtube.com/watch?v=123",
            action="type_yt_video"
        )
        self.assertEqual(req.fps, "auto")
        self.assertEqual(req.aspect_ratio, "9:16")
        self.assertEqual(req.quality, "1080")
        self.assertIsNone(req.segments)

    def test_process_request_model_segments(self):
        req = ProcessRequest(
            url="https://youtube.com/watch?v=123",
            action="type_yt_clip",
            segments=[
                {"start_time": "01:00", "end_time": "02:00"},
                {"start_time": "05:00", "end_time": "07:00"}
            ]
        )
        self.assertEqual(len(req.segments), 2)
        self.assertEqual(req.segments[0]["start_time"], "01:00")
        self.assertEqual(req.segments[1]["end_time"], "07:00")

    @patch("luna.app._run_ffmpeg")
    def test_extract_clip_segment(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        out = extract_clip_segment("/fake/full.mp4", "/fake/out.mp4", 60.0, 120.0, ratio="9:16")
        self.assertEqual(out, "/fake/out.mp4")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("-ss", cmd)
        self.assertIn("-t", cmd)
        self.assertIn("-vf", cmd)

    def test_process_request_model_custom_fps_and_ratio(self):
        req = ProcessRequest(
            url="https://youtube.com/watch?v=123",
            action="type_yt_video",
            aspect_ratio="3:4",
            fps="60",
            quality="720"
        )
        self.assertEqual(req.fps, "60")
        self.assertEqual(req.aspect_ratio, "3:4")
        self.assertEqual(req.quality, "720")

    def test_format_video_target_noop(self):
        path = "/fake/path/video.mp4"
        res = format_video_target(path, ratio="original", fps="auto")
        self.assertEqual(res, path)

    @patch("luna.app._run_ffmpeg")
    def test_format_video_target_crop_and_fps(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        res = format_video_target("/fake/path/myvideo.mp4", ratio="9:16", fps="60")
        self.assertIn("myvideo_9x16_60fps.mp4", res)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("-vf", cmd)
        vf_idx = cmd.index("-vf")
        self.assertIn("crop=ih*9/16:ih,scale=1080:1920", cmd[vf_idx + 1])
        self.assertIn("-r", cmd)
        r_idx = cmd.index("-r")
        self.assertEqual(cmd[r_idx + 1], "60")
        self.assertIn("+faststart", cmd)

    @patch("luna.app._run_ffmpeg")
    def test_extract_clip_segment_original_ratio(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        out = extract_clip_segment("/fake/full.mp4", "/fake/out.mp4", 10.0, 25.0, ratio="original")
        self.assertEqual(out, "/fake/out.mp4")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertNotIn("-vf", cmd)

    @patch("luna.app._get_encoder_flags", return_value=["-c:v", "h264_amf", "-quality", "speed"])
    @patch("luna.app._run_ffmpeg")
    def test_extract_clip_segment_uses_detected_hw_encoder(self, mock_run, mock_flags):
        mock_run.return_value = MagicMock(returncode=0)
        extract_clip_segment("/fake/full.mp4", "/fake/out.mp4", 10.0, 25.0, ratio="9:16")
        mock_flags.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("h264_amf", cmd)
        self.assertIn("-quality", cmd)
        self.assertNotIn("libx264", cmd)

    @patch("luna.app._get_encoder_flags", return_value=["-c:v", "h264_amf", "-quality", "speed"])
    @patch("luna.app._run_ffmpeg")
    def test_format_video_target_uses_detected_hw_encoder(self, mock_run, mock_flags):
        mock_run.return_value = MagicMock(returncode=0)
        out = format_video_target("/fake/in.mp4", ratio="9:16", fps="60")
        self.assertEqual(out.replace("\\", "/"), "/fake/in_9x16_60fps.mp4")
        mock_flags.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("h264_amf", cmd)
        self.assertIn("-quality", cmd)
        self.assertNotIn("libx264", cmd)

    def test_youtube_short_detection_and_policy_enforcement(self):
        self.assertTrue(is_youtube_short_url("https://www.youtube.com/shorts/dQw4w9WgXcQ"))
        self.assertTrue(is_youtube_short_url("https://youtube.com/shorts/abc_123-xyz?feature=share"))
        self.assertFalse(is_youtube_short_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertFalse(is_youtube_short_url("https://evil.example/shorts/dQw4w9WgXcQ"))

        video_req = ProcessRequest(
            url="https://www.youtube.com/shorts/dQw4w9WgXcQ",
            action="type_yt_video",
            aspect_ratio="9:16",
        )
        normalized = _enforce_youtube_short_policy(video_req)
        self.assertEqual(normalized.aspect_ratio, "original")

        ai_req = ProcessRequest(
            url="https://www.youtube.com/shorts/dQw4w9WgXcQ",
            action="type_yt_ai_clip",
        )
        with self.assertRaises(HTTPException) as ctx:
            _enforce_youtube_short_policy(ai_req)
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
