import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from luna import storage_manager
from luna import vault_service
from luna.app import OUTPUT_DIR, app, _save_single_media_to_vault


class TestApiVault(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.env_patch = patch.dict(os.environ, {"MEDIA_STORAGE_DIR": self.test_dir})
        self.env_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env_patch.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_vault_empty(self):
        """GET /api/vault should return 200 and empty schema when vault is empty."""
        response = self.client.get("/api/vault")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn("items", data)
        self.assertIn("stats", data)
        self.assertEqual(data["items"], [])

        stats = data["stats"]
        self.assertEqual(stats["total_files"], 0)
        self.assertEqual(stats["total_bytes"], 0)
        self.assertEqual(stats["total_mb"], 0.0)
        self.assertEqual(stats["total_gb"], 0.0)
        self.assertEqual(stats["storage_root"], os.path.abspath(self.test_dir))

    def test_get_vault_with_items(self):
        """GET /api/vault should return 200, items sorted descending, and storage stats."""
        cat_dir = os.path.join(self.test_dir, "02-YouTube-Full")
        os.makedirs(cat_dir, exist_ok=True)

        video_file = os.path.join(cat_dir, "2026-09-07_TestVideo.mp4")
        with open(video_file, "wb") as f:
            f.write(b"0" * 1024)

        item = {
            "id": "yt_sample_1",
            "title": "Test Video",
            "filename": "2026-09-07_TestVideo.mp4",
            "file_path": video_file,
            "url": "/media-vault/02-YouTube-Full/2026-09-07_TestVideo.mp4",
            "platform": "youtube",
            "category": "02-YouTube-Full",
            "saved_at": 1700000000.0,
        }
        vault_service.save_media_metadata(cat_dir, item)

        response = self.client.get("/api/vault")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["id"], "yt_sample_1")
        self.assertEqual(data["items"][0]["title"], "Test Video")

        stats = data["stats"]
        self.assertEqual(stats["total_files"], 1)
        self.assertEqual(stats["total_bytes"], 1024)

    def test_delete_vault_item_existing(self):
        """DELETE /api/vault/{item_id} should delete file, metadata, and return success."""
        cat_dir = os.path.join(self.test_dir, "03-Instagram-Reels")
        os.makedirs(cat_dir, exist_ok=True)

        reel_file = os.path.join(cat_dir, "2026-09-07_Reel.mp4")
        with open(reel_file, "wb") as f:
            f.write(b"reel content")

        item = {
            "id": "reel_item_to_delete",
            "title": "Reel to Delete",
            "filename": "2026-09-07_Reel.mp4",
            "file_path": reel_file,
        }
        vault_service.save_media_metadata(cat_dir, item)
        self.assertTrue(os.path.exists(reel_file))

        response = self.client.delete("/api/vault/reel_item_to_delete")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "deleted", "item_id": "reel_item_to_delete"},
        )

        # File and item should no longer exist
        self.assertFalse(os.path.exists(reel_file))
        vault_resp = self.client.get("/api/vault")
        self.assertEqual(vault_resp.json()["items"], [])

    def test_delete_vault_item_not_found(self):
        """DELETE /api/vault/{item_id} should return 404 if item does not exist."""
        response = self.client.delete("/api/vault/non_existent_item_id")
        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.json())

    def test_open_file_success(self):
        """POST /api/vault/open-file should return 200 and invoke explorer on Windows."""
        dummy_file = os.path.join(self.test_dir, "test_file.mp4")
        with open(dummy_file, "wb") as f:
            f.write(b"media bytes")

        with patch("subprocess.Popen") as mock_popen:
            response = self.client.post(
                "/api/vault/open-file",
                json={"file_path": dummy_file},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {"status": "success", "file": dummy_file},
            )

            if sys.platform == "win32":
                expected_cmd = ["explorer.exe", f"/select,{os.path.abspath(os.path.normpath(dummy_file))}"]
                mock_popen.assert_called_once_with(expected_cmd)

    def test_download_file_rejects_path_traversal(self):
        """GET /api/download-file should reject filenames that escape the job folder."""
        response = self.client.get("/api/download-file/job123/..%5Capp.py")
        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())

    def test_download_file_success(self):
        """GET /api/download-file should serve files inside the requested job folder."""
        job_id = "safejob123"
        job_dir = os.path.join(OUTPUT_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)
        file_path = os.path.join(job_dir, "video.mp4")
        try:
            with open(file_path, "wb") as f:
                f.write(b"video bytes")

            response = self.client.get(f"/api/download-file/{job_id}/video.mp4")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"video bytes")
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    def test_open_file_rejects_path_outside_vault(self):
        """POST /api/vault/open-file should not open arbitrary local files."""
        fd, outside_file = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        try:
            response = self.client.post(
                "/api/vault/open-file",
                json={"file_path": outside_file},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("detail", response.json())
        finally:
            if os.path.exists(outside_file):
                os.remove(outside_file)

    def test_open_file_not_found(self):
        """POST /api/vault/open-file should return 404 when file does not exist."""
        ghost_path = os.path.join(self.test_dir, "non_existent.mp4")
        response = self.client.post(
            "/api/vault/open-file",
            json={"file_path": ghost_path},
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.json())

    def test_open_file_invalid_payload(self):
        """POST /api/vault/open-file should return 422 on invalid payload."""
        response = self.client.post("/api/vault/open-file", json={})
        self.assertEqual(response.status_code, 422)

    def test_open_folder_success(self):
        """POST /api/vault/open-folder should return 200."""
        with patch("subprocess.Popen") as mock_popen:
            response = self.client.post("/api/vault/open-folder")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "success")

    def test_open_folder_rejects_path_outside_vault(self):
        response = self.client.post(
            "/api/vault/open-folder", json={"folder": os.path.dirname(self.test_dir)}
        )
        self.assertEqual(response.status_code, 400)

    def test_save_single_media_to_vault_integration(self):
        """Verify _save_single_media_to_vault copies file and registers to vault."""
        source_media = os.path.join(self.test_dir, "source_vid.mp4")
        with open(source_media, "wb") as f:
            f.write(b"source content")

        item = _save_single_media_to_vault(
            file_path=source_media,
            category_key="tiktok_video",
            action="type_tt_video",
            platform="tiktok",
            prefix="",
        )
        self.assertIsNotNone(item)
        self.assertTrue(os.path.exists(item["file_path"]))
        self.assertEqual(item["category"], "04-TikTok-Clean")
        self.assertEqual(item["platform"], "tiktok")

        vault_items = vault_service.list_vault_items()
        self.assertEqual(len(vault_items), 1)
        self.assertEqual(vault_items[0]["id"], item["id"])


if __name__ == "__main__":
    unittest.main()
