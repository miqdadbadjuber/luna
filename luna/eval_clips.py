# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

"""Clip quality evaluation: run a fixed set of videos, then score human grades.

    python -m luna.eval_clips run --videos eval/videos.json --out eval/runs/<label>
    python -m luna.eval_clips report eval/runs/<label> [--minimum eval/minimum.json]

`run` writes results.json and a grades.csv with empty grade columns. A person fills
those in with y or n, and `report` turns them into pass rates.
"""
import argparse
import csv
import json
import os
import sys
import time
from typing import Dict, List, Optional

CRITERIA = ("complete_thought", "stands_alone", "caption_true", "would_post")
GRADE_COLUMNS = ("video", "clip", "start", "end", "score", "title", "caption", *CRITERIA, "notes")


def _config() -> Dict:
    from .clipper.config import gemini_model, llm_provider, openai_model, transcribe_provider

    provider = llm_provider()
    return {
        "llm_provider": provider,
        "model": openai_model() if provider == "openai" else gemini_model(),
        "transcribe_provider": transcribe_provider(),
    }


def run(videos_path: str, out_dir: str, num_clips: int = 5, quality: str = "720") -> Dict:
    from .clipper import generate_shorts

    with open(videos_path, encoding="utf-8") as f:
        videos = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    results = {"config": {**_config(), "num_clips": num_clips, "quality": quality}, "videos": []}
    rows: List[Dict] = []
    for video in videos:
        started = time.time()
        entry = {**video, "clips": [], "error": None}
        try:
            out = generate_shorts(video["url"], num_clips=num_clips, download_format=quality,
                                  out_dir=os.path.join(out_dir, video["id"]))
            entry["transcribe_provider"] = out.get("transcribe_provider")
            for i, clip in enumerate(out.get("shorts", []), 1):
                entry["clips"].append({k: clip.get(k) for k in ("title", "start_time", "end_time", "score", "caption", "clip_url", "error")})
                rows.append({
                    "video": video["id"], "clip": i, "start": clip.get("start_time"), "end": clip.get("end_time"),
                    "score": clip.get("score"), "title": clip.get("title"), "caption": clip.get("caption"),
                })
        except Exception as e:  # one bad video must not end the whole run
            entry["error"] = str(e)
        entry["seconds"] = round(time.time() - started, 1)
        results["videos"].append(entry)
        print(f"[eval] {video['id']}: {len(entry['clips'])} clips in {entry['seconds']}s {entry['error'] or ''}", flush=True)

    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "grades.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=GRADE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return results


def _yes(value: str) -> Optional[bool]:
    value = (value or "").strip().lower()
    if value in ("y", "yes", "1", "true"):
        return True
    if value in ("n", "no", "0", "false"):
        return False
    return None


def report(run_dir: str) -> Dict:
    with open(os.path.join(run_dir, "grades.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    summary: Dict = {"clips": len(rows), "graded": 0, "pass_rate": {}}
    for name in CRITERIA:
        marks = [_yes(r.get(name, "")) for r in rows]
        marks = [m for m in marks if m is not None]
        summary["pass_rate"][name] = round(sum(marks) / len(marks), 3) if marks else None
    graded = [r for r in rows if _yes(r.get("would_post", "")) is not None]
    summary["graded"] = len(graded)

    def mean_score(post: bool) -> Optional[float]:
        scores = [float(r["score"]) for r in graded if _yes(r["would_post"]) is post and r.get("score")]
        return round(sum(scores) / len(scores), 1) if scores else None

    # If clips people would post do not score higher, the score is not telling users anything.
    summary["mean_score_would_post"] = mean_score(True)
    summary["mean_score_would_not_post"] = mean_score(False)
    return summary


def below_minimum(summary: Dict, minimum: Dict) -> List[str]:
    failures = []
    for name, floor in minimum.get("pass_rate", {}).items():
        rate = summary["pass_rate"].get(name)
        if rate is None or rate < floor:
            failures.append(f"{name}: {rate} < {floor}")
    gap = minimum.get("score_gap")
    if gap is not None:
        good, bad = summary["mean_score_would_post"], summary["mean_score_would_not_post"]
        if good is None or bad is None or good - bad < gap:
            failures.append(f"score gap between posted and not posted clips is under {gap}")
    return failures


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m luna.eval_clips")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="run the pipeline on every video in the list")
    p_run.add_argument("--videos", required=True)
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--clips", type=int, default=5)
    p_run.add_argument("--quality", default="720")
    p_report = sub.add_parser("report", help="summarize the grades of a run")
    p_report.add_argument("run_dir")
    p_report.add_argument("--minimum", help="JSON with pass_rate floors and score_gap; exit 1 when not met")
    args = parser.parse_args(argv)

    if args.command == "run":
        run(args.videos, args.out, args.clips, args.quality)
        return 0
    summary = report(args.run_dir)
    print(json.dumps(summary, indent=2))
    if args.minimum:
        with open(args.minimum, encoding="utf-8") as f:
            failures = below_minimum(summary, json.load(f))
        for line in failures:
            print(f"below minimum: {line}")
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
