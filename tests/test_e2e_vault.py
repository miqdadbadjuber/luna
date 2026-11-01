# tests/test_e2e_vault.py
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app import app
from storage_manager import get_storage_root, get_category_folder
from vault_service import save_media_metadata, list_vault_items, delete_vault_item, get_storage_stats


class TestEndToEndVault(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.storage_root = get_storage_root()
        self.test_clip_dir = os.path.join(self.storage_root, "01-AI-Clips", "2026-09-07_E2E_Test_Video")
        os.makedirs(self.test_clip_dir, exist_ok=True)
        
        self.test_file_path = os.path.join(self.test_clip_dir, "clip_01_virality-95.mp4")
        with open(self.test_file_path, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42") # Minimal mock mp4 header
            f.write(b"0" * 1024)

        self.test_item_id = "e2e_test_clip_01"
        self.mock_item = {
            "id": self.test_item_id,
            "title": "E2E Test Video Podcast AI Clip",
            "platform": "youtube",
            "action": "youtube_ai_clip",
            "filename": "clip_01_virality-95.mp4",
            "file_path": self.test_file_path,
            "video_url": f"/media-vault/01-AI-Clips/2026-09-07_E2E_Test_Video/clip_01_virality-95.mp4",
            "download_url": f"/media-vault/01-AI-Clips/2026-09-07_E2E_Test_Video/clip_01_virality-95.mp4",
            "duration": 42,
            "filesize_bytes": os.path.getsize(self.test_file_path),
            "virality_score": 95,
            "caption": "This is an AI-generated viral hook for testing the media vault.",
        }
        save_media_metadata(self.test_clip_dir, self.mock_item)

    def tearDown(self):
        # Clean up any leftover test folder
        if os.path.exists(self.test_clip_dir):
            try:
                shutil.rmtree(self.test_clip_dir)
            except Exception:
                pass

    def test_full_vault_lifecycle(self):
        # 1. Verify GET /api/vault returns our test item
        res = self.client.get("/api/vault")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("items", data)
        self.assertIn("stats", data)
        
        found = any(item["id"] == self.test_item_id for item in data["items"])
        self.assertTrue(found, "Created E2E test item must be present in GET /api/vault")

        # 2. Verify static mount /media-vault can stream the file
        video_res = self.client.get(self.mock_item["video_url"])
        self.assertEqual(video_res.status_code, 200)
        self.assertGreater(len(video_res.content), 0)

        # 3. Verify POST /api/vault/open-folder
        with patch("subprocess.Popen"):
            folder_res = self.client.post("/api/vault/open-folder")
        self.assertEqual(folder_res.status_code, 200)
        self.assertEqual(folder_res.json()["status"], "success")

        # 4. Verify DELETE /api/vault/{item_id} removes physical file and metadata
        del_res = self.client.delete(f"/api/vault/{self.test_item_id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(del_res.json()["status"], "deleted")
        self.assertFalse(os.path.exists(self.test_file_path), "Physical file must be deleted from disk")

        # 5. Verify item no longer appears in GET /api/vault
        res_after = self.client.get("/api/vault")
        self.assertEqual(res_after.status_code, 200)
        found_after = any(item["id"] == self.test_item_id for item in res_after.json()["items"])
        self.assertFalse(found_after, "Deleted item must not be present in vault")

    def test_html_template_renders_and_contains_all_vault_components(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # Navbar tabs
        self.assertIn("tabBtnStudio", html)
        self.assertIn("tabBtnVault", html)
        self.assertIn("vaultBadgeCount", html)

        # Vault main view
        self.assertIn("section-vault", html)
        self.assertIn("vaultGalleryGrid", html)
        self.assertIn("vaultSearchInput", html)
        self.assertIn("vaultStoragePath", html)
        self.assertIn("vaultTotalFiles", html)
        self.assertIn("vaultTotalSize", html)

        # Delete confirmation modal
        self.assertIn("deleteModal", html)
        self.assertIn("deleteModalTitle", html)
        self.assertIn("deleteModalPath", html)
        self.assertIn("deleteModalConfirmBtn", html)

        # Studio background engine
        self.assertIn("studioBackgroundContainer", html)


if __name__ == "__main__":
    unittest.main()
