"""Simulated agent session against Luna's MCP server.

Starts a fake Luna (canned HTTP answers, no download or AI call), launches
luna/mcp_server.py over stdio the way Claude Code does, and runs the flow an
agent would: check_setup, clip_video, job_status until done, get_clips with
save_to. Prints each call and its answer.

    python -m tests.mcp_simulation
"""

import asyncio
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcp import ClientSession, StdioServerParameters, stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOB_ID = "a1b2c3d4"
CLIPS = [
    {"type": "video", "title": "Why compound interest feels slow", "start_time": 62.0, "end_time": 101.5,
     "score": 91, "caption": "The first ten years do almost nothing. Then they do everything.",
     "filename": "short_1.mp4", "download_url": f"/api/download-file/{JOB_ID}/short_1.mp4"},
    {"type": "video", "title": "The one budget rule that sticks", "start_time": 240.0, "end_time": 275.0,
     "score": 87, "caption": "Pay yourself first, then spend what is left.",
     "filename": "short_2.mp4", "download_url": f"/api/download-file/{JOB_ID}/short_2.mp4"},
]


class FakeLuna(BaseHTTPRequestHandler):
    """Answers the Luna endpoints the MCP server calls. A job finishes on its third poll."""

    polls = 0

    def log_message(self, *args):
        pass

    def _send(self, code, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/octet-stream" if raw is not None else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/settings":
            return self._send(200, {
                "llm_provider": "gemini", "transcribe_provider": "groq",
                "gemini_api_key": "AIz...wxyz", "has_gemini_api_key": True,
                "has_groq_api_key": True, "has_openai_api_key": False,
                "status": {"ffmpeg": True, "storage": True, "cookies": {"exists": False}},
            })
        if self.path == f"/api/status/{JOB_ID}":
            FakeLuna.polls += 1
            stages = [("downloading", 20.0), ("selecting", 70.0)]
            if FakeLuna.polls <= len(stages):
                stage, progress = stages[FakeLuna.polls - 1]
                return self._send(200, {"id": JOB_ID, "status": "processing", "stage": stage,
                                        "progress": progress, "results": [], "logs": [f"{stage}..."]})
            return self._send(200, {"id": JOB_ID, "status": "completed", "stage": "done", "progress": 100.0,
                                    "results": CLIPS, "project_id": "proj_demo", "logs": ["Done."]})
        if self.path.startswith(f"/api/download-file/{JOB_ID}/"):
            return self._send(200, None, raw=b"fake mp4 bytes")
        if self.path.startswith("/api/status/"):
            return self._send(404, {"detail": "Job not found"})
        return self._send(404, {"detail": "Not Found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/process":
            if "youtube.com" not in body.get("url", "") and "youtu.be" not in body.get("url", ""):
                return self._send(400, {"detail": "Only YouTube, Instagram and TikTok links are supported."})
            FakeLuna.polls = 0
            return self._send(200, {"job_id": JOB_ID, "status": "queued"})
        return self._send(404, {"detail": "Not Found"})


def start_fake_luna():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLuna)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _payload(result):
    """The tool's answer as Python data, or the error text for a failed call."""
    text = "".join(getattr(c, "text", "") for c in result.content)
    if getattr(result, "is_error", False) or getattr(result, "isError", False):
        return {"error": text}
    try:
        return json.loads(text)
    except ValueError:
        return text


async def run(save_to, echo=print):
    """Run the agent flow and return {tool_name: last answer}."""
    server, url = start_fake_luna()
    params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(ROOT, "luna", "mcp_server.py")],
        env={**os.environ, "LUNA_URL": url},
    )
    answers = {}

    async def call(session, name, args=None):
        echo(f"> {name}({json.dumps(args or {})})")
        answers[name] = _payload(await session.call_tool(name, args or {}))
        echo(json.dumps(answers[name], indent=2))
        return answers[name]

    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                answers["tools"] = sorted(t.name for t in tools.tools)
                echo("tools: " + ", ".join(answers["tools"]))
                await call(session, "check_setup")
                answers["rejected"] = _payload(await session.call_tool(
                    "clip_video", {"url": "https://example.com/video"}))
                echo("> clip_video on an unsupported site -> " + json.dumps(answers["rejected"]))
                job = await call(session, "clip_video", {
                    "url": "https://www.youtube.com/watch?v=example", "num_clips": 2})
                while not (await call(session, "job_status", {"job_id": job["job_id"]}))["finished"]:
                    pass  # a real agent waits 15 to 30 seconds here
                await call(session, "get_clips", {"job_id": job["job_id"], "save_to": save_to})
    finally:
        server.shutdown()
    return answers


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as folder:
        asyncio.run(run(os.path.join(folder, "clips")))
