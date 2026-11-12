# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

import http.server
import socket
import threading
import unittest

from luna.start import HOST, choose_port


def _serve(body: bytes):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer((HOST, 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class ChoosePortTest(unittest.TestCase):
    def test_free_port_is_used_as_is(self):
        with socket.socket() as s:
            s.bind((HOST, 0))
            port = s.getsockname()[1]
        self.assertEqual(choose_port(port, fixed=False), (port, False))

    def test_other_app_on_port_moves_to_next_free_one(self):
        server = _serve(b"<html><title>Something else</title></html>")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        chosen, running = choose_port(port, fixed=False)
        self.assertFalse(running)
        self.assertGreater(chosen, port)

    def test_other_app_on_fixed_port_stops_with_message(self):
        server = _serve(b"<html><title>Something else</title></html>")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        with self.assertRaises(SystemExit) as stop:
            choose_port(port, fixed=True)
        self.assertIn(str(port), str(stop.exception))

    def test_running_luna_is_reused(self):
        server = _serve(b"<html><title>Luna: AI Video Clipper & Downloader</title></html>")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        self.assertEqual(choose_port(port, fixed=False), (port, True))


if __name__ == "__main__":
    unittest.main()
