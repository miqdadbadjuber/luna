import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import re
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

import yt_dlp

from luna.clipper import fast_http


_RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$")


def _make_handler(payload: bytes, allow_range: bool, range_calls: list):
    class _RangeHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            range_hdr = self.headers.get("Range")
            if allow_range and range_hdr:
                match = _RANGE_RE.match(range_hdr.strip())
                if match:
                    start = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) else len(payload) - 1
                    end = min(end, len(payload) - 1)
                    body = payload[start : end + 1]
                    range_calls.append((start, end))
                    self.send_response(206)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            pass

    return _RangeHandler


class TestFastHttp(unittest.TestCase):
    def test_build_chunk_plan_covers_entire_file_contiguously(self):
        total = 5_123_457
        chunks = fast_http._build_chunk_plan(total, workers=4)
        self.assertGreaterEqual(len(chunks), 4)
        self.assertEqual(chunks[0][0], 0)
        self.assertEqual(chunks[-1][1], total - 1)
        for prev, curr in zip(chunks, chunks[1:]):
            self.assertEqual(prev[1] + 1, curr[0])

    def test_build_request_headers_normalizes_accept_encoding_and_cookies(self):
        jar = MagicMock()
        jar.get_cookie_header.return_value = "SID=abc"
        hdrs = fast_http._build_request_headers(
            {"http_headers": {"accept-encoding": "gzip, br", "User-Agent": "UA"}},
            "https://example.test/video.mp4",
            cookiejar=jar,
        )
        self.assertEqual(hdrs["Accept-Encoding"], "identity")
        self.assertNotIn("accept-encoding", hdrs)
        self.assertEqual(hdrs["Cookie"], "SID=abc")

    def test_create_youtube_dl_respects_mock_module(self):
        sentinel = object()
        fake = MagicMock(YoutubeDL=MagicMock(return_value=sentinel))
        res = fast_http.create_youtube_dl({"quiet": True}, ytdlp_mod=fake)
        self.assertIs(res, sentinel)

    def test_multi_connection_range_download_assembles_exact_bytes(self):
        payload = os.urandom(3 * 1024 * 1024 + 137)
        expected_sha = hashlib.sha256(payload).hexdigest()
        range_calls = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(payload, True, range_calls))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/video.mp4"
            with tempfile.TemporaryDirectory() as tmp:
                out_path = os.path.join(tmp, "video.mp4")
                events = []
                with fast_http.create_youtube_dl(
                    {"quiet": True, "no_warnings": True, "outtmpl": out_path},
                    ytdlp_mod=yt_dlp,
                ) as ydl:
                    fd = fast_http.build_fast_http_fd(yt_dlp)(ydl, ydl.params)
                    fd.add_progress_hook(lambda d: events.append(dict(d)))
                    ok = fd.real_download(out_path, {"url": url, "http_headers": {}})
                self.assertTrue(ok)
                self.assertTrue(os.path.exists(out_path))
                self.assertFalse(os.path.exists(out_path + ".part"))
                with open(out_path, "rb") as f:
                    self.assertEqual(hashlib.sha256(f.read()).hexdigest(), expected_sha)
                self.assertGreater(len(range_calls), 2)
                self.assertEqual(events[-1]["status"], "finished")
        finally:
            server.shutdown()
            server.server_close()

    def test_fallback_when_origin_lacks_range_support(self):
        payload = b"fallback-bytes-" * 20000
        range_calls = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(payload, False, range_calls))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/small.mp4"
            with tempfile.TemporaryDirectory() as tmp:
                out_path = os.path.join(tmp, "small.mp4")
                with fast_http.create_youtube_dl(
                    {"quiet": True, "no_warnings": True, "outtmpl": out_path},
                    ytdlp_mod=yt_dlp,
                ) as ydl:
                    fd = fast_http.build_fast_http_fd(yt_dlp)(ydl, ydl.params)
                    ok = fd.real_download(out_path, {"url": url, "http_headers": {}})
                self.assertTrue(ok)
                with open(out_path, "rb") as f:
                    self.assertEqual(f.read(), payload)
                self.assertEqual(range_calls, [])
        finally:
            server.shutdown()
            server.server_close()

    def test_cancellation_cleans_up_part_file_and_reraises(self):
        payload = os.urandom(3 * 1024 * 1024)
        range_calls = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(payload, True, range_calls))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/cancel.mp4"
            with tempfile.TemporaryDirectory() as tmp:
                out_path = os.path.join(tmp, "cancel.mp4")
                with fast_http.create_youtube_dl(
                    {"quiet": True, "no_warnings": True, "outtmpl": out_path},
                    ytdlp_mod=yt_dlp,
                ) as ydl:
                    fd = fast_http.build_fast_http_fd(yt_dlp)(ydl, ydl.params)

                    def abort_hook(d):
                        raise RuntimeError("CANCELLED_BY_USER")

                    fd.add_progress_hook(abort_hook)
                    with self.assertRaisesRegex(RuntimeError, "CANCELLED_BY_USER"):
                        fd.real_download(out_path, {"url": url, "http_headers": {}})
                self.assertFalse(os.path.exists(out_path))
                self.assertFalse(os.path.exists(out_path + ".part"))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
