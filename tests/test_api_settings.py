import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from luna.app import app

class TestApiSettings(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # The settings endpoints rewrite .env, so point them away from the developer's real file.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env_path = os.path.join(tmp.name, ".env")
        base_dir = patch("luna.app.BASE_DIR", tmp.name)
        base_dir.start()
        self.addCleanup(base_dir.stop)
        environ = patch.dict(os.environ)
        environ.start()
        self.addCleanup(environ.stop)

    @patch("requests.get")
    def test_groq_key_test_does_not_save_until_settings_are_saved(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        new_test_key = "gsk_auto_save_verified_test_12345"
        res = self.client.post("/api/settings/test-key", json={
            "provider": "groq",
            "api_key": new_test_key
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("valid"))
        self.assertFalse(data.get("saved", False))

        # Testing validates the candidate without replacing the configured key.
        self.assertNotEqual(os.environ.get("GROQ_API_KEY"), new_test_key)
        saved = self.client.post("/api/settings", json={"groq_api_key": new_test_key})
        self.assertEqual(saved.status_code, 200)

        # Verify in memory os.environ after explicit save.
        self.assertEqual(os.environ.get("GROQ_API_KEY"), new_test_key)
        from luna.clipper.config import require_groq_key
        self.assertEqual(require_groq_key(), new_test_key)

        # Verify in .env file
        with open(self.env_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(f"GROQ_API_KEY={new_test_key}", content)

    def test_env_write_survives_a_bind_mounted_file(self):
        """.env is bind-mounted in Docker, where os.replace fails with EBUSY.

        The save must fall back to writing through the file instead of raising 500.
        """
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write("OPENAI_MODEL=gpt-4o-mini\n")

        with patch("luna.app.os.replace", side_effect=OSError(16, "Device or resource busy")):
            res = self.client.post("/api/settings", json={"openai_model": "gpt-4.1"})

        self.assertEqual(res.status_code, 200)
        with open(self.env_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("OPENAI_MODEL=gpt-4.1", content)

    def test_env_write_falls_back_when_app_dir_is_not_writable(self):
        """Compose runs the container as LUNA_UID, which may not own the mounted /app.

        Staging .env.tmp then fails with EACCES even though .env itself is writable,
        so the save must write through the file instead of returning 500.
        """
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write("OPENAI_MODEL=gpt-4o-mini\n")

        with patch("luna.app.os.access", return_value=False):
            res = self.client.post("/api/settings", json={"openai_model": "gpt-4.1"})

        self.assertEqual(res.status_code, 200)
        with open(self.env_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("OPENAI_MODEL=gpt-4.1", content)

    @patch("subprocess.Popen")
    def test_open_folder_calls_explorer_on_windows(self, mock_popen):
        res = self.client.post("/api/vault/open-folder")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")
        mock_popen.assert_called_once()

    @patch("subprocess.run")
    def test_browse_folder_endpoint(self, mock_subproc):
        mock_res = MagicMock()
        mock_res.stdout = "D:\\SelectedFolder\n"
        mock_subproc.return_value = mock_res

        with patch("os.path.exists", return_value=True):
            res = self.client.post("/api/settings/browse-folder")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data.get("status"), "success")
            self.assertTrue(data.get("path").endswith("SelectedFolder"))

    def test_storage_migration(self):
        import shutil
        old_dir = tempfile.mkdtemp()
        new_dir = tempfile.mkdtemp()

        try:
            # Create dummy media file in old_dir
            clip_dir = os.path.join(old_dir, "01-AI-Clips")
            os.makedirs(clip_dir, exist_ok=True)
            dummy_file = os.path.join(clip_dir, "test_clip.mp4")
            with open(dummy_file, "w") as f:
                f.write("dummy video data")

            with patch.dict(os.environ, {"MEDIA_STORAGE_DIR": old_dir}):
                res = self.client.post("/api/settings", json={
                    "storage_dir": new_dir,
                    "migrate_files": True
                })
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data.get("status"), "saved")
                self.assertIsNotNone(data.get("migrated"))

                # Verify file was moved to new_dir
                migrated_file = os.path.join(new_dir, "01-AI-Clips", "test_clip.mp4")
                self.assertTrue(os.path.exists(migrated_file))
        finally:
            shutil.rmtree(old_dir, ignore_errors=True)
            shutil.rmtree(new_dir, ignore_errors=True)

    def test_clip_language_setting_roundtrip_and_validation(self):
        from luna.app import ProcessRequest

        os.environ.pop("CLIP_OUTPUT_LANGUAGE", None)
        self.assertEqual(self.client.get("/api/settings").json().get("clip_language"), "id")

        res = self.client.post("/api/settings", json={"clip_language": "en"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.client.get("/api/settings").json().get("clip_language"), "en")
        with open(self.env_path, "r", encoding="utf-8") as f:
            self.assertIn("CLIP_OUTPUT_LANGUAGE=en", f.read())

        bad = self.client.post("/api/settings", json={"clip_language": "th"})
        self.assertEqual(bad.status_code, 400)

        req = ProcessRequest(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", action="type_yt_ai_clip", clip_language="English")
        self.assertEqual(req.clip_language, "en")
        with self.assertRaises(ValueError):
            ProcessRequest(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", action="type_yt_ai_clip", clip_language="ml")

    @patch("luna.app._open_windows_explorer")
    def test_open_folder_invokes_foreground_explorer_helper_on_windows(self, mock_open):
        with patch("luna.app.sys.platform", "win32"):
            res = self.client.post("/api/vault/open-folder")
        self.assertEqual(res.status_code, 200)
        mock_open.assert_called_once()

if __name__ == "__main__":
    unittest.main()
