import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from luna import vault_service
from luna.app import app, jobs


class TestVaultProjects(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.env_patch = patch.dict(os.environ, {"MEDIA_STORAGE_DIR": self.test_dir})
        self.env_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env_patch.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_vault_projects_empty(self):
        """GET /api/vault/projects returns empty project list and next index 1."""
        response = self.client.get("/api/vault/projects")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("projects", data)
        self.assertIn("stats", data)
        self.assertIn("next_workspace_index", data)
        self.assertEqual(data["projects"], [])
        self.assertEqual(data["next_workspace_index"], 1)

    def test_save_and_list_projects(self):
        """Create project with files and verify retrieval via API."""
        ws_dir = os.path.join(self.test_dir, "01-AI-Clips", "Workspace 01")
        os.makedirs(ws_dir, exist_ok=True)
        file_path = os.path.join(ws_dir, "clip_1.mp4")
        with open(file_path, "wb") as f:
            f.write(b"0" * 2048)

        project_data = {
            "project_id": "proj_test_01",
            "workspace_name": "Workspace 01",
            "platform": "youtube",
            "action": "type_yt_ai_clip",
            "source_title": "Podcast Episode 1",
            "created_at": time.time(),
            "folder_path": ws_dir,
            "files": [
                {
                    "id": "f_01",
                    "title": "Clip 1",
                    "filename": "clip_1.mp4",
                    "file_path": file_path,
                    "url": "/media-vault/01-AI-Clips/Workspace 01/clip_1.mp4",
                    "file_size": 2048,
                    "type": "video",
                }
            ],
        }
        vault_service.save_project_metadata(ws_dir, project_data)

        response = self.client.get("/api/vault/projects")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["projects"]), 1)
        self.assertEqual(data["projects"][0]["workspace_name"], "Workspace 01")
        self.assertEqual(data["projects"][0]["source_title"], "Podcast Episode 1")
        self.assertEqual(len(data["projects"][0]["files"]), 1)
        self.assertEqual(data["next_workspace_index"], 2)

    def test_rename_project(self):
        """PATCH /api/vault/project/{id}/rename should update workspace_name."""
        ws_dir = os.path.join(self.test_dir, "02-YouTube-Full", "Workspace 01")
        os.makedirs(ws_dir, exist_ok=True)
        project_data = {
            "project_id": "proj_rename_1",
            "workspace_name": "Workspace 01",
            "platform": "youtube",
            "action": "type_yt_video",
            "source_title": "Original Title",
            "created_at": time.time(),
            "folder_path": ws_dir,
            "files": [],
        }
        vault_service.save_project_metadata(ws_dir, project_data)

        rename_resp = self.client.patch(
            "/api/vault/project/proj_rename_1/rename",
            json={"new_name": "My Edited Workspace"},
        )
        self.assertEqual(rename_resp.status_code, 200)
        self.assertEqual(rename_resp.json()["status"], "renamed")

        # Verify updated name via GET
        get_resp = self.client.get("/api/vault/projects")
        projects = get_resp.json()["projects"]
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["workspace_name"], "My Edited Workspace")

    def test_rename_legacy_project_virtual_id(self):
        """PATCH /api/vault/project/{id}/rename should succeed for legacy folders without project_id."""
        legacy_dir = os.path.join(self.test_dir, "01-AI-Clips", "2026-09-07_Rahasia-Sukses-Miliarder-Podcast")
        os.makedirs(legacy_dir, exist_ok=True)
        clip_file = os.path.join(legacy_dir, "clip_01.mp4")
        with open(clip_file, "wb") as f:
            f.write(b"0" * 1024)

        # Legacy flat metadata without project_id
        import json
        with open(os.path.join(legacy_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump([
                {
                    "id": "clip_01",
                    "title": "Podcast Clip",
                    "platform": "youtube",
                    "action": "youtube_ai_clip",
                    "file_path": clip_file,
                    "saved_at": time.time(),
                }
            ], f)

        # Rename using the deterministic virtual ID the API hands out for this folder.
        virtual_id = vault_service._generate_folder_project_id(legacy_dir)
        rename_resp = self.client.patch(
            f"/api/vault/project/{virtual_id}/rename",
            json={"new_name": "Project 1"},
        )
        self.assertEqual(rename_resp.status_code, 200)
        self.assertEqual(rename_resp.json()["status"], "renamed")

        # Verify updated name
        get_resp = self.client.get("/api/vault/projects")
        projects = get_resp.json()["projects"]
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["workspace_name"], "Project 1")


    def test_delete_project(self):
        """DELETE /api/vault/project/{id} should remove project and files."""
        ws_dir = os.path.join(self.test_dir, "03-Instagram-Reels", "Workspace 01")
        os.makedirs(ws_dir, exist_ok=True)
        vid_file = os.path.join(ws_dir, "reels.mp4")
        with open(vid_file, "wb") as f:
            f.write(b"0" * 1024)

        project_data = {
            "project_id": "proj_del_1",
            "workspace_name": "Workspace 01",
            "platform": "instagram",
            "action": "type_ig_reels",
            "source_title": "Reels Video",
            "created_at": time.time(),
            "folder_path": ws_dir,
            "files": [
                {
                    "id": "f_reels_1",
                    "title": "Reels Video",
                    "filename": "reels.mp4",
                    "file_path": vid_file,
                    "url": "/media-vault/03-Instagram-Reels/Workspace 01/reels.mp4",
                    "file_size": 1024,
                    "type": "video",
                }
            ],
        }
        vault_service.save_project_metadata(ws_dir, project_data)

        del_resp = self.client.delete("/api/vault/project/proj_del_1")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json()["status"], "deleted")
        self.assertFalse(os.path.exists(vid_file))

        get_resp = self.client.get("/api/vault/projects")
        self.assertEqual(len(get_resp.json()["projects"]), 0)

    def test_cancel_job(self):
        """POST /api/cancel/{job_id} should set status to cancelled."""
        job_id = "test_cancel_123"
        jobs[job_id] = {
            "id": job_id,
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "action": "type_yt_ai_clip",
            "workspace_name": "Workspace 01",
            "status": "processing",
            "stage": "downloading",
            "cancelled": False,
            "logs": [],
            "results": [],
            "error": None,
        }

        cancel_resp = self.client.post(f"/api/cancel/{job_id}")
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.json()["status"], "cancelled")
        self.assertTrue(jobs[job_id]["cancelled"])
        self.assertEqual(jobs[job_id]["status"], "cancelled")

    def test_process_request_accepts_workspace_name(self):
        """POST /api/process accepts custom workspace_name."""
        payload = {
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "action": "type_yt_video",
            "workspace_name": "Workspace Keren",
            "quality": "1080",
        }
        with patch("luna.app._worker_process"):
            resp = self.client.post("/api/process", json=payload)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            job_id = data.get("job_id")
            self.assertIn(job_id, jobs)
            self.assertEqual(jobs[job_id]["workspace_name"], "Workspace Keren")

    def test_merge_into_existing_workspace(self):
        """_save_project_to_vault merges files into an existing workspace without creating duplicates."""
        from luna.app import _save_project_to_vault

        # Setup initial workspace with 1 file
        src_file1 = os.path.join(self.test_dir, "test1.mp4")
        with open(src_file1, "wb") as f:
            f.write(b"video data 1")

        proj1 = _save_project_to_vault(
            workspace_name="Music Project",
            action="type_yt_video",
            platform="youtube",
            source_title="Video 1",
            files_to_save=[{
                "file_path": src_file1,
                "title": "Video 1",
                "type": "video",
            }]
        )
        self.assertIsNotNone(proj1)
        self.assertEqual(len(proj1["files"]), 1)
        orig_proj_id = proj1["project_id"]

        # Add a second file using the same workspace name with different casing.
        src_file2 = os.path.join(self.test_dir, "test2.mp3")
        with open(src_file2, "wb") as f:
            f.write(b"audio data 2")

        proj2 = _save_project_to_vault(
            workspace_name="MUSIC PROJECT",
            action="type_yt_mp3",
            platform="youtube",
            source_title="Song 2",
            files_to_save=[{
                "file_path": src_file2,
                "title": "Song 2",
                "type": "audio",
            }]
        )
        self.assertIsNotNone(proj2)
        # Should retain original project ID and merged files list (length 2)
        self.assertEqual(proj2["project_id"], orig_proj_id)
        self.assertEqual(len(proj2["files"]), 2)

        # API should return only 1 project with 2 files
        api_resp = self.client.get("/api/vault/projects")
        self.assertEqual(api_resp.status_code, 200)
        projects = api_resp.json()["projects"]
        self.assertEqual(len(projects), 1)
        self.assertEqual(len(projects[0]["files"]), 2)


if __name__ == "__main__":
    unittest.main()

