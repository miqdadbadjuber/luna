import unittest
from unittest.mock import patch, MagicMock
from app import ProcessRequest, format_video_target, extract_clip_segment, parse_timestamp


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

    @patch("subprocess.run")
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

    @patch("subprocess.run")
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

    @patch("subprocess.run")
    def test_extract_clip_segment_original_ratio(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        out = extract_clip_segment("/fake/full.mp4", "/fake/out.mp4", 10.0, 25.0, ratio="original")
        self.assertEqual(out, "/fake/out.mp4")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertNotIn("-vf", cmd)


if __name__ == "__main__":
    unittest.main()
