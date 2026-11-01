import os
import unittest
from fastapi.testclient import TestClient

from app import app, _save_project_to_vault, create_progress_hook, jobs
from shorts_generator.highlights import clean_caption


class TestTranscriptAndFactualPipeline(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_clean_caption_strictly_removes_hashtags_and_emojis(self):
        # Multiple hashtags, emojis, and en/em dashes
        raw = "The secret to business success without major capital! — watch this now #business #viral #fyp 🚀🔥"
        cleaned = clean_caption(raw)
        self.assertNotIn("#", cleaned)
        self.assertNotIn("🚀", cleaned)
        self.assertNotIn("🔥", cleaned)
        self.assertNotIn("—", cleaned)
        self.assertLessEqual(len(cleaned), 90)
        self.assertTrue(cleaned.startswith("The secret to business success"))

    def test_api_check_transcript_endpoint(self):
        res = self.client.get("/api/check-transcript?url=https://www.youtube.com/watch?v=kJQP7kiw5Fk")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("has_transcript", data)
        self.assertIn("provider", data)

    def test_progress_hook_clears_eta_and_sets_ai_clip_progress(self):
        job_id = "test_job_factual"
        jobs[job_id] = {
            "action": "type_yt_ai_clip",
            "progress": 10.0,
            "download_speed": "5.0 MB/s",
            "download_eta": "00:05",
            "download_frags": "1/2 frag",
        }
        hook = create_progress_hook(job_id)
        hook({"status": "finished"})
        self.assertEqual(jobs[job_id]["download_speed"], "")
        self.assertEqual(jobs[job_id]["download_eta"], "")
        self.assertEqual(jobs[job_id]["download_frags"], "")
        self.assertEqual(jobs[job_id]["progress"], 25.0)

    def test_save_project_to_vault_saves_channel_and_provider(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_file = os.path.join(tmpdir, "clip_1.mp4")
            with open(dummy_file, "w") as f:
                f.write("test")

            target_ws_dir = os.path.join(tmpdir, "vault_target")
            os.makedirs(target_ws_dir, exist_ok=True)

            with patch("app.get_workspace_folder", return_value=target_ws_dir), \
                 patch("app.get_storage_root", return_value=tmpdir), \
                 patch("app.list_vault_projects", return_value=[]):
                proj = _save_project_to_vault(
                    workspace_name="Factual Workspace",
                    action="type_yt_ai_clip",
                    platform="youtube",
                    source_title="Testing Factual Source",
                    files_to_save=[{
                        "file_path": dummy_file,
                        "title": "Clip 1",
                        "caption": "Short concise caption without tag",
                    }],
                    channel="Ferry Irwandi",
                    transcribe_provider="Groq Cloud Whisper",
                )
                self.assertIsNotNone(proj)
                self.assertEqual(proj.get("channel"), "Ferry Irwandi")
                self.assertEqual(proj.get("transcribe_provider"), "Groq Cloud Whisper")


if __name__ == "__main__":
    unittest.main()
