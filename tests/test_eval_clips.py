import csv
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from luna import eval_clips


def _clip(start, score):
    return {"title": f"t{start}", "start_time": start, "end_time": start + 20, "score": score,
            "caption": "c", "clip_url": f"/x/{start}.mp4"}


class TestEvalClips(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.videos = os.path.join(self.tmp.name, "videos.json")
        with open(self.videos, "w") as f:
            json.dump([{"id": "a", "url": "https://youtu.be/a"}, {"id": "b", "url": "https://youtu.be/b"}], f)
        self.out = os.path.join(self.tmp.name, "run")

    def _run(self):
        def fake(url, **kwargs):
            if url.endswith("/b"):
                raise RuntimeError("download failed")
            return {"shorts": [_clip(10, 92), _clip(40, 90)], "transcribe_provider": "fake"}

        with patch("luna.clipper.generate_shorts", side_effect=fake):
            return eval_clips.run(self.videos, self.out, num_clips=2)

    def _grade(self, rows):
        path = os.path.join(self.out, "grades.csv")
        with open(path) as f:
            graded = list(csv.DictReader(f))
        for row, marks in zip(graded, rows):
            row.update(marks)
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=eval_clips.GRADE_COLUMNS)
            writer.writeheader()
            writer.writerows(graded)

    def test_run_records_clips_and_keeps_going_after_a_failed_video(self):
        results = self._run()
        self.assertEqual([len(v["clips"]) for v in results["videos"]], [2, 0])
        self.assertEqual(results["videos"][1]["error"], "download failed")
        with open(os.path.join(self.out, "grades.csv")) as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([(r["video"], r["clip"], r["score"]) for r in rows], [("a", "1", "92"), ("a", "2", "90")])
        self.assertEqual(rows[0]["would_post"], "")

    def test_report_gives_pass_rates_and_score_by_grade(self):
        self._run()
        self._grade([
            {"complete_thought": "y", "stands_alone": "y", "caption_true": "y", "would_post": "y"},
            {"complete_thought": "n", "stands_alone": "y", "caption_true": "", "would_post": "n"},
        ])
        summary = eval_clips.report(self.out)
        self.assertEqual(summary["pass_rate"], {"complete_thought": 0.5, "stands_alone": 1.0, "caption_true": 1.0, "would_post": 0.5})
        self.assertEqual((summary["mean_score_would_post"], summary["mean_score_would_not_post"]), (92.0, 90.0))

        # A 2 point gap is too small to mean anything, and half the clips cut mid-thought.
        failures = eval_clips.below_minimum(summary, {"pass_rate": {"complete_thought": 0.8}, "score_gap": 5})
        self.assertEqual(len(failures), 2)
        self.assertEqual(eval_clips.below_minimum(summary, {"pass_rate": {"stands_alone": 0.8}}), [])

    def test_ungraded_run_does_not_pass_a_minimum(self):
        self._run()
        summary = eval_clips.report(self.out)
        self.assertIsNone(summary["pass_rate"]["would_post"])
        self.assertTrue(eval_clips.below_minimum(summary, {"pass_rate": {"would_post": 0.5}}))


if __name__ == "__main__":
    unittest.main()
