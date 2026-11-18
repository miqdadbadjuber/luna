import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

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
        with patch("subprocess.Popen"):
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

    def test_rename_vault_item_api_preserves_extension_and_reports_errors(self):
        """PATCH /api/vault/item/{item_id}/rename locks extension and returns clear errors."""
        ws_dir = os.path.join(self.test_dir, "02-YouTube-Full", "WS_API")
        os.makedirs(ws_dir, exist_ok=True)
        vid1 = os.path.join(ws_dir, "Original.mp4")
        vid2 = os.path.join(ws_dir, "Sibling.mp4")
        with open(vid1, "wb") as f:
            f.write(b"vid1 bytes")
        with open(vid2, "wb") as f:
            f.write(b"vid2 bytes")

        vault_service.save_project_metadata(ws_dir, {
            "project_id": "proj_api_1",
            "workspace_name": "API WS",
            "files": [
                {"id": "api_f1", "title": "Original.mp4", "filename": "Original.mp4", "file_path": vid1},
                {"id": "api_f2", "title": "Sibling.mp4", "filename": "Sibling.mp4", "file_path": vid2},
            ],
        })

        res = self.client.patch("/api/vault/item/api_f1/rename", json={"new_name": "Updated Video"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "renamed")
        self.assertEqual(body["item"]["filename"], "Updated Video.mp4")
        self.assertTrue(os.path.exists(os.path.join(ws_dir, "Updated Video.mp4")))

        conflict = self.client.patch("/api/vault/item/api_f1/rename", json={"new_name": "Sibling"})
        self.assertEqual(conflict.status_code, 409)

        invalid = self.client.patch("/api/vault/item/api_f1/rename", json={"new_name": "???"})
        self.assertEqual(invalid.status_code, 400)

        empty = self.client.patch("/api/vault/item/api_f1/rename", json={"new_name": "   "})
        self.assertEqual(empty.status_code, 422)

        missing = self.client.patch("/api/vault/item/does_not_exist/rename", json={"new_name": "Anything"})
        self.assertEqual(missing.status_code, 404)

    def test_rename_clip_title_only_api_preserves_file_and_urls(self):
        """PATCH /api/vault/item/{item_id}/rename with title_only=True updates title without disk rename."""
        ws_dir = os.path.join(self.test_dir, "01-AI-Clipper", "Clip_API_WS")
        os.makedirs(ws_dir, exist_ok=True)
        clip_path = os.path.join(ws_dir, "clip_01.mp4")
        with open(clip_path, "wb") as f:
            f.write(b"clip bytes")

        orig_url = "/media-vault/01-AI-Clipper/Clip_API_WS/clip_01.mp4"
        vault_service.save_project_metadata(ws_dir, {
            "project_id": "proj_clip_api",
            "workspace_name": "Clip API WS",
            "files": [{
                "id": "clip_api_1",
                "title": "Original Hook",
                "filename": "clip_01.mp4",
                "file_path": clip_path,
                "url": orig_url,
            }],
        })

        res = self.client.patch(
            "/api/vault/item/clip_api_1/rename",
            json={"new_name": "Updated Viral Title?!", "title_only": True},
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "renamed")
        self.assertEqual(body["item"]["title"], "Updated Viral Title?!")
        self.assertEqual(body["item"]["filename"], "clip_01.mp4")
        self.assertEqual(body["item"]["url"], orig_url)
        self.assertTrue(os.path.exists(clip_path))

    def test_storage_stats_and_migration_exclude_temp_job_dirs(self):
        """Temp job folders inside shared output/ are excluded from Workspace stats and migration."""
        from luna import storage_manager

        fallback_dir = os.path.join(self.test_dir, "shared_output")
        new_dir = os.path.join(self.test_dir, "new_vault")
        os.makedirs(os.path.join(fallback_dir, "c0514b82"), exist_ok=True)
        with open(os.path.join(fallback_dir, "c0514b82", "job.json"), "w", encoding="utf-8") as f:
            f.write('{"job": {"id": "c0514b82"}}')
        with open(os.path.join(fallback_dir, "c0514b82", "source.mp4"), "wb") as f:
            f.write(b"tempbytes")
        with open(os.path.join(fallback_dir, "stray.srt"), "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,000\nhi\n")

        ws_dir = os.path.join(fallback_dir, "02-YouTube-Full", "WsOne")
        os.makedirs(ws_dir, exist_ok=True)
        saved_file = os.path.join(ws_dir, "saved.mp4")
        with open(saved_file, "wb") as f:
            f.write(b"12345")
        vault_service.save_project_metadata(ws_dir, {
            "project_id": "proj_ws_one",
            "workspace_name": "WsOne",
            "files": [{
                "id": "v1",
                "title": "Saved Video",
                "filename": "saved.mp4",
                "file_path": saved_file,
                "url": "/media-vault/02-YouTube-Full/WsOne/saved.mp4",
            }],
        })

        with patch.object(storage_manager, "FALLBACK_PATH", fallback_dir), \
                patch.dict(os.environ, {"MEDIA_STORAGE_DIR": fallback_dir}):
            storage_manager.invalidate_storage_root_cache()
            stats = vault_service.get_storage_stats()
            self.assertEqual(stats["total_files"], 1)
            self.assertEqual(stats["total_bytes"], 5)

            mig = storage_manager.migrate_storage(fallback_dir, new_dir)
            self.assertEqual(mig["migrated_files"], 2)  # saved.mp4 + meta.json
            self.assertTrue(os.path.exists(os.path.join(new_dir, "02-YouTube-Full", "WsOne", "saved.mp4")))
            self.assertFalse(os.path.exists(os.path.join(new_dir, "c0514b82")))
            self.assertTrue(os.path.exists(os.path.join(fallback_dir, "c0514b82", "source.mp4")))

        with patch.object(storage_manager, "FALLBACK_PATH", fallback_dir), \
                patch.dict(os.environ, {"MEDIA_STORAGE_DIR": new_dir}):
            storage_manager.invalidate_storage_root_cache()
            self.assertEqual(vault_service.delete_vault_project("proj_ws_one"), "deleted")
            self.assertEqual(vault_service.get_storage_stats()["total_files"], 0)

        storage_manager.invalidate_storage_root_cache()


if __name__ == "__main__":
    unittest.main()
