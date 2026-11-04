import os
import sys
import types
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from luna.app import app, _save_project_to_vault, create_progress_hook, jobs
from luna.clipper.highlights import clean_caption

TRANSCRIPT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _fake_transcript_module(transcripts):
    """Stand-in for youtube_transcript_api; records the video id it was asked about."""
    module = types.ModuleType("youtube_transcript_api")
    module.seen_video_ids = []

    class YouTubeTranscriptApi:
        def list(self, video_id):
            module.seen_video_ids.append(video_id)
            return list(transcripts)

    module.YouTubeTranscriptApi = YouTubeTranscriptApi
    return module


def _failing_transcript_module():
    """Stand-in whose transcript listing raises, as the real client does when blocked."""
    module = types.ModuleType("youtube_transcript_api")

    class YouTubeTranscriptApi:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("transcript service unavailable")

    module.YouTubeTranscriptApi = YouTubeTranscriptApi
    return module


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

    def test_api_check_transcript_reports_subtitle_availability(self):
        available = _fake_transcript_module([{"text": "hello"}])
        with patch.dict(sys.modules, {"youtube_transcript_api": available}):
            res = self.client.get("/api/check-transcript", params={"url": TRANSCRIPT_URL})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["has_transcript"], True)
        self.assertEqual(data["provider"], "YouTube Subtitle Scraper")
        self.assertTrue(data["note"].startswith("Official YouTube transcript"))
        self.assertEqual(available.seen_video_ids, ["dQw4w9WgXcQ"])

        unavailable = _fake_transcript_module([])
        with patch.dict(sys.modules, {"youtube_transcript_api": unavailable}):
            res = self.client.get("/api/check-transcript", params={"url": TRANSCRIPT_URL})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["has_transcript"], False)
        self.assertNotEqual(data["provider"], "YouTube Subtitle Scraper")
        self.assertTrue(data["note"].startswith("No official transcript"))

    def test_api_check_transcript_stays_200_when_the_check_raises(self):
        # Failure inside the subtitle lookup must not surface as a 5xx.
        with patch.dict(sys.modules, {"youtube_transcript_api": _failing_transcript_module()}):
            res = self.client.get("/api/check-transcript", params={"url": TRANSCRIPT_URL})
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json().get("has_transcript"), bool)

        # Failure of the lookup as a whole (bad extraction, network, unexpected error).
        with patch("luna.clipper.downloader._extract_youtube_video_id", side_effect=RuntimeError("boom")):
            res = self.client.get("/api/check-transcript", params={"url": TRANSCRIPT_URL})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data.get("has_transcript"), bool)
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
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_file = os.path.join(tmpdir, "clip_1.mp4")
            with open(dummy_file, "w") as f:
                f.write("test")

            target_ws_dir = os.path.join(tmpdir, "vault_target")
            os.makedirs(target_ws_dir, exist_ok=True)

            with patch("luna.app.get_workspace_folder", return_value=target_ws_dir), \
                 patch("luna.app.get_storage_root", return_value=tmpdir), \
                 patch("luna.app.list_vault_projects", return_value=[]):
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
