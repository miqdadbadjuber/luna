# Clip quality evaluation

A fixed set of videos, graded by a person, so a prompt or model change can be compared with the last one instead of judged on one video.

1. Copy `videos.example.json` to `videos.json` and list 10 to 20 videos: podcast, tutorial, vlog, news and non-English speech, with and without YouTube subtitles.
2. Run them with the provider and model you want to measure:

   ```bash
   python -m luna.eval_clips run --videos eval/videos.json --out eval/runs/2026-11-gpt-4o-mini
   ```

   This calls the real providers and downloads every video, so it costs API quota. `runs/` is ignored by git because it holds the clips.
3. Watch each clip and fill `grades.csv` with `y` or `n`:

   | Column | Question |
   | --- | --- |
   | `complete_thought` | Does it start and end on a complete thought, without cutting mid-sentence? |
   | `stands_alone` | Does it make sense without the rest of the video? |
   | `caption_true` | Is the caption true to what was said? |
   | `would_post` | Would you post it? |

4. Summarize, and check against the minimum:

   ```bash
   python -m luna.eval_clips report eval/runs/2026-11-gpt-4o-mini --minimum eval/minimum.json
   ```

`report` prints the pass rate per question and the mean model score for clips graded `would_post=y` and `n`. If those two means are close, the score does not tell users which clip is better, and the UI should stop calling it a virality score.

`minimum.json` is a starting proposal, not a measured bar. Set it from the first graded run. Keep `grades.csv` from each run you want to compare against, since the clips themselves are not committed.
