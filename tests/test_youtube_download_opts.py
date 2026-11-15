import tempfile
import unittest
from unittest.mock import MagicMock, patch

from luna.app import get_ytdl_base_opts
from luna.clipper import downloader


class _Captured(Exception):
    pass


class TestYoutubeDownloadOpts(unittest.TestCase):
    def assert_h264_with_warnings(self, opts):
        self.assertEqual(opts["format_sort"], ["res", "vcodec:h264"])
        # no_warnings hid the JS challenge failure that made YouTube throttle downloads
        self.assertNotIn("no_warnings", opts)
        self.assertEqual(opts["socket_timeout"], 15)
        self.assertEqual(opts["retries"], 5)
        self.assertEqual(opts["fragment_retries"], 5)
        self.assertEqual(opts["concurrent_fragment_downloads"], 12)
        self.assertEqual(opts["http_chunk_size"], 10 * 1024 * 1024)
        self.assertEqual(opts["buffersize"], 64 * 1024)

    def test_app_downloads(self):
        self.assert_h264_with_warnings(get_ytdl_base_opts({"format": "best"}))

    def test_clipper_download(self):
        seen = {}

        def fake_ydl(opts):
            seen.update(opts)
            raise _Captured

        fake = MagicMock(YoutubeDL=fake_ydl)
        with tempfile.TemporaryDirectory() as out, patch.object(downloader, "_import_ytdlp", return_value=fake):
            with self.assertRaises(_Captured):
                downloader.download_youtube_local("https://www.youtube.com/watch?v=aqz-KE-bpKQ", out_dir=out)
        self.assert_h264_with_warnings(seen)


if __name__ == "__main__":
    unittest.main()
