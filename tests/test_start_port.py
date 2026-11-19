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

    def test_supervisor_restarts_in_place_without_opening_duplicate_browser(self):
        import os
        from unittest.mock import MagicMock, patch
        import luna.start as start_mod

        procs = [MagicMock(), MagicMock()]
        procs[0].wait.return_value = start_mod.RESTART_EXIT_CODE
        procs[1].wait.return_value = 0
        spawned_envs = []

        def fake_popen(cmd, env=None, **kwargs):
            spawned_envs.append(dict(env or {}))
            return procs[len(spawned_envs) - 1]

        with patch.object(start_mod.subprocess, "Popen", side_effect=fake_popen), \
                patch.object(start_mod, "_wait_for_port_release") as mock_wait, \
                patch.object(start_mod.threading, "Thread") as mock_thread:
            rc = start_mod.run_supervised_server(8000, "http://localhost:8000", no_browser=False)

        self.assertEqual(rc, 0)
        self.assertEqual(len(spawned_envs), 2)
        self.assertEqual(spawned_envs[0]["LUNA_SUPERVISED"], "1")
        self.assertEqual(spawned_envs[0]["LUNA_NO_BROWSER"], "1")
        self.assertEqual(spawned_envs[1]["LUNA_SUPERVISED"], "1")
        self.assertEqual(spawned_envs[1]["LUNA_NO_BROWSER"], "1")
        mock_wait.assert_called_once_with(8000)
        # Browser open thread should be started at most once on initial boot, never on restart.
        self.assertEqual(mock_thread.call_count, 1)

        # Already-running branch must also respect LUNA_NO_BROWSER=1.
        with patch.dict(os.environ, {"LUNA_NO_BROWSER": "1", "LUNA_PORT": "8000"}), \
                patch.object(start_mod, "choose_port", return_value=(8000, True)), \
                patch.object(start_mod.webbrowser, "open") as mock_open:
            self.assertEqual(start_mod.main(), 0)
            mock_open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
