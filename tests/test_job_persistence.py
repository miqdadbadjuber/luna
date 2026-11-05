import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import luna.app as app_module
from luna.app import app


class TestJobPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(app_module, "OUTPUT_DIR", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.job_id = "abcd1234"
        self.addCleanup(self._forget)

    def _forget(self):
        for store in (app_module.jobs, app_module.job_requests, app_module.job_cancel_events):
            store.pop(self.job_id, None)
        app_module.job_finished.discard(self.job_id)

    def _write_saved_job(self, status):
        folder = os.path.join(self.tmp.name, self.job_id)
        os.makedirs(folder)
        job = {"id": self.job_id, "status": status, "stage": "downloading", "logs": [], "results": []}
        request = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "action": "type_yt_video"}
        with open(os.path.join(folder, "job.json"), "w") as f:
            json.dump({"job": job, "request": request}, f)
        return os.path.join(folder, "job.json")

    def test_save_writes_the_job_without_leaving_a_temp_file(self):
        app_module.jobs[self.job_id] = {"id": self.job_id, "status": "processing"}
        app_module._save_job(self.job_id)
        folder = os.path.join(self.tmp.name, self.job_id)
        self.assertEqual(os.listdir(folder), ["job.json"])
        with open(os.path.join(folder, "job.json")) as f:
            self.assertEqual(json.load(f)["job"]["status"], "processing")

    def test_a_job_running_at_restart_comes_back_failed_and_retryable(self):
        path = self._write_saved_job("processing")
        self.assertEqual(app_module._restore_jobs(), 1)

        status = TestClient(app).get(f"/api/status/{self.job_id}").json()
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error"], app_module.INTERRUPTED_ERROR)
        self.assertTrue(status["retryable"])
        with open(path) as f:
            self.assertEqual(json.load(f)["job"]["status"], "failed")

    def test_a_finished_job_is_restored_unchanged(self):
        self._write_saved_job("completed")
        app_module._restore_jobs()
        status = TestClient(app).get(f"/api/status/{self.job_id}").json()
        self.assertEqual(status["status"], "completed")
        self.assertFalse(status["retryable"])

    def test_a_corrupt_job_file_is_skipped(self):
        path = self._write_saved_job("processing")
        with open(path, "w") as f:
            f.write("{half a fi")
        self.assertEqual(app_module._restore_jobs(), 0)
        self.assertNotIn(self.job_id, app_module.jobs)

    def test_retry_runs_the_job_again_in_the_same_folder(self):
        self._write_saved_job("processing")
        app_module._restore_jobs()
        with patch.object(app_module, "_worker_process") as worker, \
                patch.object(app_module, "external_url_problem", return_value=None):
            res = TestClient(app).post(f"/api/retry/{self.job_id}")
        self.assertEqual(res.json(), {"job_id": self.job_id, "status": "queued"})
        job_id, req = worker.call_args.args
        self.assertEqual((job_id, req.action), (self.job_id, "type_yt_video"))
        self.assertIsNone(app_module.jobs[self.job_id]["error"])

    def test_only_a_failed_job_can_be_retried(self):
        self._write_saved_job("completed")
        app_module._restore_jobs()
        with patch.object(app_module, "_worker_process") as worker:
            res = TestClient(app).post(f"/api/retry/{self.job_id}")
        self.assertEqual(res.status_code, 409)
        worker.assert_not_called()
        self.assertEqual(TestClient(app).post("/api/retry/ffffffff").status_code, 404)


if __name__ == "__main__":
    unittest.main()
