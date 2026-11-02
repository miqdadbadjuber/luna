import unittest
from luna.app import create_progress_hook, jobs


class TestProgressTracking(unittest.TestCase):
    def setUp(self):
        self.job_id = "test_job_123"
        jobs[self.job_id] = {
            "id": self.job_id,
            "status": "queued",
            "stage": "queued",
            "progress": 0.0,
            "download_speed": "",
            "download_eta": "",
            "download_frags": "",
            "cancelled": False,
        }

    def tearDown(self):
        if self.job_id in jobs:
            del jobs[self.job_id]

    def test_progress_hook_downloading(self):
        hook = create_progress_hook(self.job_id)
        d = {
            "status": "downloading",
            "downloaded_bytes": 5000000,
            "total_bytes": 10000000,
            "speed": 2500000,
            "eta": 2,
        }
        hook(d)
        job = jobs[self.job_id]
        self.assertEqual(job["progress"], 50.0)
        self.assertIn("MB/s", job["download_speed"])
        self.assertEqual(job["download_eta"], "00:02")

    def test_progress_hook_finished(self):
        hook = create_progress_hook(self.job_id)
        hook({"status": "finished"})
        job = jobs[self.job_id]
        self.assertEqual(job["progress"], 100.0)
        self.assertEqual(job["download_speed"], "")
        self.assertEqual(job["download_eta"], "")

    def test_progress_hook_cancelled(self):
        hook = create_progress_hook(self.job_id)
        jobs[self.job_id]["cancelled"] = True
        with self.assertRaises(RuntimeError):
            hook({"status": "downloading"})


if __name__ == "__main__":
    unittest.main()
