import os
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app import app, BASE_DIR

class TestApiSettingsAutoSave(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.env_path = os.path.join(BASE_DIR, ".env")
        self.original_env = None
        self.original_groq_env = os.environ.get("GROQ_API_KEY")
        if os.path.exists(self.env_path):
            with open(self.env_path, "r", encoding="utf-8") as f:
                self.original_env = f.read()

    def tearDown(self):
        if self.original_env is not None:
            with open(self.env_path, "w", encoding="utf-8") as f:
                f.write(self.original_env)
        if self.original_groq_env is None:
            os.environ.pop("GROQ_API_KEY", None)
        else:
            os.environ["GROQ_API_KEY"] = self.original_groq_env

    @patch("requests.get")
    def test_groq_key_test_auto_saves_to_env(self, mock_get):
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
        self.assertTrue(data.get("saved"))

        # Verify in memory os.environ
        self.assertEqual(os.environ.get("GROQ_API_KEY"), new_test_key)
        from shorts_generator.config import require_groq_key
        self.assertEqual(require_groq_key(), new_test_key)

        # Verify in .env file
        with open(self.env_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(f"GROQ_API_KEY={new_test_key}", content)

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
        import tempfile
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

if __name__ == "__main__":
    unittest.main()
