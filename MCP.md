# Driving Luna from an AI agent (MCP)

`luna/mcp_server.py` is a [Model Context Protocol](https://modelcontextprotocol.io) server. It lets an agent such as Claude Code turn a video link into short clips with Luna, while the agent handles everything around it: finding the video, writing the post, publishing it.

The server only calls Luna's HTTP API. URL checks, the AI clip pipeline and rendering all stay in Luna, so the agent gets exactly what the web UI gets.

```
agent (Claude Code) --stdio--> luna/mcp_server.py --HTTP--> Luna (python -m luna)
```

## Setup

1. Run Luna as usual (`./start.sh`, `python -m luna` or Docker) and set up AI Clip in Settings.
2. Install the MCP package into Luna's environment:

   ```bash
   .venv/bin/pip install -r requirements-mcp.txt
   ```

3. Register the server with Claude Code. Use absolute paths, since Claude Code starts it from another directory:

   ```bash
   claude mcp add luna -e LUNA_URL=http://127.0.0.1:8000 -- \
     /path/to/luna/.venv/bin/python /path/to/luna/luna/mcp_server.py
   ```

   Other MCP clients take the same command and `LUNA_URL` in their config file.

4. In Claude Code, run `/mcp` and check that `luna` is connected.

The server imports nothing from Luna, so any Python 3.12 with `mcp` installed can run it.

### Luna on another machine

Luna has no login, so do not expose its port. Forward it over SSH and keep `LUNA_URL` on localhost:

```bash
ssh -N -L 8000:127.0.0.1:8000 my-server
```

Pass `save_to` to `get_clips` so the clips are copied to the machine the agent runs on.

## Tools

| Tool | What it does |
| --- | --- |
| `check_setup` | AI provider, transcription provider, FFmpeg, storage and cookies. API keys are reported as set or not set, never their values. |
| `video_info` | Title, duration and thumbnail of a link, without downloading. |
| `clip_video` | Starts a job and returns its `job_id` at once. Without `segments`, Luna's AI picks `num_clips` moments and writes a caption for each. With `segments`, it cuts the given ranges. |
| `job_status` | Status, stage, progress, error and whether a failed job can be retried. |
| `get_clips` | For a completed job: title, time range, score, caption and download URL of each clip. `save_to` downloads them into a local folder. |
| `retry_job` | Runs a failed job again with the same settings, reusing finished downloads. |
| `cancel_job` | Stops a running job and deletes its partial files. |
| `list_projects` | Workspaces in the media vault. |

Clipping takes minutes, so `clip_video` does not wait. The agent polls `job_status` every 15 to 30 seconds until `finished` is true. Errors come back as messages the agent can act on. For example, "YouTube asked this request to sign in. Upload cookies in Settings, then try again." tells the agent to ask for cookies.

Only process videos you have the rights to use. AI Clip sends the audio or transcript to the providers chosen in Settings.

## Example prompt

> Find a recent YouTube talk on personal budgeting under 20 minutes. Check Luna's setup, make 3 vertical clips from it with Luna, save them to ./clips and give me each clip's caption.

## Simulation

`tests/mcp_simulation.py` runs that flow end to end without a network, an API key or a real download. It starts a fake Luna, launches the MCP server over stdio as Claude Code would, and prints every call:

```bash
pip install -r requirements-dev.txt
python -m tests.mcp_simulation
```

Shortened output:

```
tools: cancel_job, check_setup, clip_video, get_clips, job_status, list_projects, retry_job, video_info
> check_setup({})
{ "llm_provider": "gemini", "transcribe_provider": "groq",
  "api_keys_set": { "openai": false, "gemini": true, "groq": true }, ... }
> clip_video on an unsupported site -> {"error": "Error executing tool clip_video: Luna answered 400: Only YouTube, Instagram and TikTok links are supported."}
> clip_video({"url": "https://www.youtube.com/watch?v=example", "num_clips": 2})
{ "job_id": "a1b2c3d4", "status": "queued", "next": "Call job_status every 15 to 30 seconds until it finishes." }
> job_status({"job_id": "a1b2c3d4"})
{ "status": "processing", "stage": "downloading", "progress": 20.0, "finished": false, ... }
> job_status({"job_id": "a1b2c3d4"})
{ "status": "completed", "progress": 100.0, "finished": true, "clip_count": 2, ... }
> get_clips({"job_id": "a1b2c3d4", "save_to": ".../clips"})
{ "clips": [
    { "title": "Why compound interest feels slow", "start_time": 62.0, "end_time": 101.5, "score": 91,
      "caption": "The first ten years do almost nothing. Then they do everything.",
      "filename": "short_1.mp4", "local_path": ".../clips/short_1.mp4", ... },
    ... ] }
```

`tests/test_mcp_server.py` runs the same simulation in CI and checks each answer.
