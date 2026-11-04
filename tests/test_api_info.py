import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from luna.app import app

class TestApiInfo(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_api_info_empty_url(self):
        res = self.client.post("/api/info", json={"url": ""})
        self.assertEqual(res.status_code, 400)

    @patch("requests.post")
    def test_api_info_youtube_innertube_duration(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "videoDetails": {
                "title": "AI Makin Canggih, Tapi Kok Makin Ngeri?",
                "lengthSeconds": "684",
                "thumbnail": {
                    "thumbnails": [
                        {"url": "https://i.ytimg.com/vi/test/hqdefault.jpg"},
                        {"url": "https://i.ytimg.com/vi/test/maxresdefault.jpg"}
                    ]
                }
            }
        }
        mock_post.return_value = mock_resp

        res = self.client.post("/api/info", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["title"], "AI Makin Canggih, Tapi Kok Makin Ngeri?")
        self.assertEqual(data["duration"], 684)
        self.assertEqual(data["platform"], "youtube")
        self.assertIn("maxresdefault.jpg", data["thumbnail"])

    def test_api_info_ssrf_blocked(self):
        # SSRF blocked targets
        malicious_urls = [
            "http://localhost:8000/api/settings",
            "http://127.0.0.1:8000/api/vault",
            "http://192.168.1.1/admin",
            "http://10.0.0.1/secrets",
            "file:///etc/passwd",
            "javascript:alert(1)"
        ]
        for bad_url in malicious_urls:
            res = self.client.post("/api/info", json={"url": bad_url})
            self.assertEqual(res.status_code, 400, f"Expected 400 for SSRF attempt: {bad_url}")

    def test_jobs_pruning(self):
        from luna.app import jobs, job_finished, _prune_old_jobs
        jobs.clear()
        job_finished.clear()
        for i in range(60):
            jobs[f"job_{i}"] = {"id": f"job_{i}", "status": "completed"}
            # Only jobs whose worker already returned may be evicted.
            job_finished.add(f"job_{i}")
        _prune_old_jobs(50)
        self.assertLessEqual(len(jobs), 50)

    def test_jobs_pruning_keeps_running_workers(self):
        from luna.app import jobs, job_finished, _prune_old_jobs
        jobs.clear()
        job_finished.clear()
        for i in range(60):
            jobs[f"job_{i}"] = {"id": f"job_{i}", "status": "completed"}
        # None of these are marked finished, so none may be evicted.
        _prune_old_jobs(50)
        self.assertEqual(len(jobs), 60)
        jobs.clear()

    def test_friendly_error_messages(self):
        from luna.app import friendly_error_message

        interrupted = OSError("[Errno 2] No such file or directory: 'video.part-Frag7'")
        self.assertIn("internet connection", friendly_error_message(interrupted))
        self.assertIn("private", friendly_error_message(RuntimeError("Private video")))
        self.assertIn("not a supported", friendly_error_message(RuntimeError("Unsupported URL")))
        self.assertEqual(friendly_error_message(RuntimeError("boom")), "boom")

    def test_frontend_format_duration_logic(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn("formatDuration", html)
        self.assertIn("previewBullet", html)
        self.assertIn("previewDuration", html)
        self.assertIn("checkAndResumeSavedJob", html)
        self.assertIn("releaseMediaLocks", html)

if __name__ == "__main__":
    unittest.main()
