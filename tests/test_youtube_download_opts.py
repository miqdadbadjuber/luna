import tempfile
import unittest
from unittest.mock import MagicMock, patch

import luna.app as app_module
from luna.app import ProcessRequest, get_ytdl_base_opts
from luna.clipper import downloader


class _Captured(Exception):
    pass


class TestYoutubeDownloadOpts(unittest.TestCase):
    def assert_tuning_with_warnings(self, opts):
        # no_warnings hid the JS challenge failure that made YouTube throttle downloads
        self.assertNotIn("no_warnings", opts)
        self.assertEqual(opts["socket_timeout"], 15)
        self.assertEqual(opts["retries"], 5)
        self.assertEqual(opts["fragment_retries"], 5)
        self.assertEqual(opts["concurrent_fragment_downloads"], 4)
        self.assertNotIn("http_chunk_size", opts)
        self.assertNotIn("buffersize", opts)

    def test_app_downloads(self):
        opts = get_ytdl_base_opts({"format": "best"})
        self.assert_tuning_with_warnings(opts)
        self.assertEqual(opts["format_sort"], ["res", "vcodec:h264"])

    def test_clipper_download(self):
        seen = {}

        def fake_ydl(opts):
            seen.update(opts)
            raise _Captured

        fake = MagicMock(YoutubeDL=fake_ydl)
        with tempfile.TemporaryDirectory() as out, patch.object(downloader, "_import_ytdlp", return_value=fake):
            with self.assertRaises(_Captured):
                downloader.download_youtube_local("https://www.youtube.com/watch?v=aqz-KE-bpKQ", out_dir=out)
        self.assert_tuning_with_warnings(seen)
        self.assertEqual(seen["format_sort"], ["res", "proto:https", "+size", "+br"])
        self.assertIn("height<=1080", seen["format"])

    def test_trimmer_uses_smallest_https_while_full_video_keeps_h264(self):
        trim_seen = {}
        full_seen = {}

        def capture_into(bucket):
            def _fake(opts):
                bucket.update(opts)
                raise _Captured
            return _fake

        with tempfile.TemporaryDirectory() as out:
            with patch.object(app_module, "create_youtube_dl", side_effect=capture_into(full_seen)):
                with self.assertRaises(_Captured):
                    app_module.download_youtube_video("https://www.youtube.com/watch?v=aqz-KE-bpKQ", out, "1080")
            self.assertEqual(full_seen["format_sort"], downloader.YOUTUBE_FORMAT_SORT)

            req = ProcessRequest(url="https://www.youtube.com/watch?v=aqz-KE-bpKQ", action="type_yt_clip")
            app_module.jobs["trim_opts_test"] = {
                "id": "trim_opts_test",
                "status": "queued",
                "stage": "queued",
                "progress": 0.0,
                "logs": [],
                "cancelled": False,
            }
            try:
                with patch.object(app_module, "OUTPUT_DIR", out), patch.object(
                    app_module, "create_youtube_dl", side_effect=capture_into(trim_seen)
                ):
                    app_module._worker_process("trim_opts_test", req)
            finally:
                app_module.jobs.pop("trim_opts_test", None)
            self.assertEqual(trim_seen["format_sort"], downloader.CLIPPER_FORMAT_SORT)

    def test_format_for_defaults_to_1080_and_honors_explicit_choice(self):
        self.assertIn("height<=1080", downloader._format_for("1080"))
        self.assertIn("height<=1080", downloader._format_for("invalid"))
        self.assertIn("height<=720", downloader._format_for("720"))


if __name__ == "__main__":
    unittest.main()
