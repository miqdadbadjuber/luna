import io
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import luna.app as app_module
from luna import updater


class TestUpdater(unittest.TestCase):
    def test_check_for_updates_archive_untracked_and_tracked(self):
        remote = {
            "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "short_sha": "aaaaaaa",
            "message": "feat: test release",
            "date": "2026-11-19T00:00:00Z",
            "url": "https://github.com/miqdadbadjuber/luna/commit/aaaaaaa",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(updater, "fetch_remote_latest", return_value=remote):
                # Untracked archive install (no .git, no .luna-version) -> offers first-time sync update
                res1 = updater.check_for_updates(tmp)
                self.assertTrue(res1["update_available"])
                self.assertEqual(res1["reason"], "untracked_install")
                self.assertEqual(res1["install_mode"], "archive")

                # Matching .luna-version -> up to date
                (Path(tmp) / updater.VERSION_MARKER_FILENAME).write_text(remote["sha"] + "\n", encoding="utf-8")
                res2 = updater.check_for_updates(tmp)
                self.assertFalse(res2["update_available"])
                self.assertEqual(res2["reason"], "up_to_date")

                # Older .luna-version -> behind_remote
                (Path(tmp) / updater.VERSION_MARKER_FILENAME).write_text("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n", encoding="utf-8")
                res3 = updater.check_for_updates(tmp)
                self.assertTrue(res3["update_available"])
                self.assertEqual(res3["reason"], "behind_remote")

    def test_check_for_updates_git_local_ahead_reports_up_to_date(self):
        remote = {
            "sha": "1111111111111111111111111111111111111111",
            "short_sha": "1111111",
            "message": "old remote commit",
            "date": "2026-11-19T00:00:00Z",
            "url": "https://github.com/miqdadbadjuber/luna/commit/1111111",
        }
        with patch.object(updater, "get_local_version", return_value=("2222222222222222222222222222222222222222", "git")), \
                patch.object(updater, "fetch_remote_latest", return_value=remote), \
                patch.object(updater, "_git_is_ancestor", return_value=True):
            res = updater.check_for_updates("/fake/repo")
        self.assertFalse(res["update_available"])
        self.assertEqual(res["reason"], "local_ahead")

    def test_archive_update_preserves_env_cookies_venv_and_output(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("luna-main/luna/hello.py", "VERSION = 2\n")
            zf.writestr("luna-main/.env", "SHOULD_NOT_OVERWRITE=1\n")
            zf.writestr("luna-main/cookies.txt", "evil\n")
            zf.writestr("luna-main/output/fake.txt", "evil\n")
        archive_bytes = buf.getvalue()

        class _FakeResp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("GEMINI_API_KEY=keep-me\n", encoding="utf-8")
            (root / "cookies.txt").write_text("my-cookies\n", encoding="utf-8")
            (root / "output").mkdir()
            (root / "output" / "video.mp4").write_bytes(b"media")
            (root / "luna").mkdir()
            (root / "luna" / "hello.py").write_text("VERSION = 1\n", encoding="utf-8")

            with patch.object(updater.urllib.request, "urlopen", return_value=_FakeResp(archive_bytes)):
                updater._apply_archive_update(
                    tmp,
                    "https://github.com/miqdadbadjuber/luna",
                    "main",
                    "deadbeef1234567890",
                )

            self.assertEqual((root / "luna" / "hello.py").read_text(encoding="utf-8"), "VERSION = 2\n")
            self.assertEqual((root / ".env").read_text(encoding="utf-8"), "GEMINI_API_KEY=keep-me\n")
            self.assertEqual((root / "cookies.txt").read_text(encoding="utf-8"), "my-cookies\n")
            self.assertTrue((root / "output" / "video.mp4").exists())
            self.assertFalse((root / "output" / "fake.txt").exists())
            self.assertEqual(
                (root / updater.VERSION_MARKER_FILENAME).read_text(encoding="utf-8").strip(),
                "deadbeef1234567890",
            )

    def test_update_api_endpoints_and_busy_job_guard(self):
        client = TestClient(app_module.app)

        fake_check = {
            "update_available": True,
            "reason": "behind_remote",
            "install_mode": "archive",
            "current_sha": "1111111",
            "current_short_sha": "1111111",
            "latest_sha": "2222222",
            "latest_short_sha": "2222222",
            "latest_message": "feat: update test",
            "latest_date": "2026-11-19T00:00:00Z",
            "commit_url": "https://github.com/miqdadbadjuber/luna/commit/2222222",
        }
        with patch.object(app_module, "check_app_updates", return_value=dict(fake_check)):
            res = client.get("/api/system/check-update")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["update_available"])

        # Active processing job blocks apply-update with 409
        app_module.jobs["busy_update_test"] = {"id": "busy_update_test", "status": "processing"}
        try:
            blocked = client.post("/api/system/apply-update", json={"auto_restart": False})
            self.assertEqual(blocked.status_code, 409)
        finally:
            app_module.jobs.pop("busy_update_test", None)

        # Clean apply-update with auto_restart=False completes cleanly
        with app_module._update_lock:
            app_module._update_state["status"] = "idle"
        with patch.object(
            app_module,
            "run_app_update",
            return_value={"install_mode": "archive", "updated_sha": "2222222", "updated_short_sha": "2222222"},
        ):
            started = client.post("/api/system/apply-update", json={"target_sha": "2222222", "auto_restart": False})
            self.assertEqual(started.status_code, 200)
            for _ in range(30):
                st = client.get("/api/system/update-status").json()
                if st["status"] in ("completed", "error"):
                    break
                time.sleep(0.05)
            self.assertEqual(st["status"], "completed")
            self.assertEqual(st["updated_short_sha"], "2222222")

    def test_supervised_restart_exits_with_restart_code_without_spawning_new_terminal(self):
        import threading
        exit_codes = []
        done = threading.Event()

        def fake_exit(code):
            exit_codes.append(code)
            done.set()

        with patch.dict(os.environ, {"LUNA_SUPERVISED": "1", "LUNA_PORT": "8000"}), \
                patch.object(updater.subprocess, "Popen") as mock_popen, \
                patch.object(updater.os, "_exit", side_effect=fake_exit), \
                patch("time.sleep"):
            updater.schedule_server_restart(".", delay_sec=0.01)
            self.assertTrue(done.wait(timeout=2.0))

        mock_popen.assert_not_called()
        self.assertEqual(exit_codes, [updater.RESTART_EXIT_CODE])


if __name__ == "__main__":
    unittest.main()
