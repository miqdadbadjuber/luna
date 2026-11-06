# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.
"""MCP server that lets an AI agent drive a running Luna through its HTTP API.

It holds no clipping logic of its own: URL checks, job handling and rendering
stay in luna/app.py. It imports nothing from Luna, so it can run from any
Python that has the `mcp` package, on the same machine as Luna or another one.

    python luna/mcp_server.py            # stdio, for Claude Code and other MCP clients
    LUNA_URL=http://127.0.0.1:8000       # where Luna listens (default shown)
"""

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Literal, Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

# Raise ToolError: its message reaches the agent, any other exception arrives as a bare failure.
FINISHED = ("completed", "failed", "cancelled")

mcp = MCPServer(
    name="luna",
    instructions=(
        "Luna turns a YouTube, Instagram or TikTok link into short clips. "
        "Call check_setup first. clip_video starts a job and returns at once; "
        "call job_status every 15 to 30 seconds until the status is completed, "
        "failed or cancelled. Then get_clips lists the clips, and save_to copies "
        "them to a local folder. A failed job with retryable true can go to retry_job. "
        "Only process videos the user has the rights to use."
    ),
)


def luna_url() -> str:
    return os.getenv("LUNA_URL", "http://127.0.0.1:8000").rstrip("/")


def _call(method: str, path: str, body: Optional[dict] = None, timeout: float = 60) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        luna_url() + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail")
        except Exception:
            detail = None
        raise ToolError(f"Luna answered {e.code}: {detail or e.reason}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ToolError(
            f"Cannot reach Luna at {luna_url()} ({getattr(e, 'reason', e)}). "
            "Start Luna with ./start.sh, or set LUNA_URL to where it runs."
        ) from None


async def _api(method: str, path: str, body: Optional[dict] = None) -> Any:
    # urllib blocks; keep it off the event loop so status polls stay responsive.
    return await asyncio.to_thread(_call, method, path, body)


def _job_path(job_id: str) -> str:
    return urllib.parse.quote(job_id.strip(), safe="")


READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


@mcp.tool(annotations=READ_ONLY)
async def check_setup() -> Dict[str, Any]:
    """Report whether Luna is reachable and ready: AI provider, transcription, FFmpeg, storage, cookies.

    Call this before the first job. API keys are reported only as set or not set.
    """
    s = await _api("GET", "/api/settings")
    return {
        "luna_url": luna_url(),
        "llm_provider": s.get("llm_provider") or "auto",
        "transcribe_provider": s.get("transcribe_provider"),
        "api_keys_set": {
            "openai": s.get("has_openai_api_key", False),
            "gemini": s.get("has_gemini_api_key", False),
            "groq": s.get("has_groq_api_key", False),
        },
        "system": s.get("status", {}),
    }


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
async def video_info(url: str) -> Dict[str, Any]:
    """Look up a video's title, duration and thumbnail without downloading it."""
    return await _api("POST", "/api/info", {"url": url})


@mcp.tool(annotations=ToolAnnotations(open_world_hint=True))
async def clip_video(
    url: str,
    num_clips: int = 5,
    aspect_ratio: Literal["9:16", "1:1", "3:4", "16:9", "original"] = "9:16",
    use_face_detect: bool = False,
    segments: Optional[List[Dict[str, str]]] = None,
    workspace_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Start a clipping job and return its job_id right away. The job runs for minutes.

    Without segments, Luna's AI picks the best moments and writes a caption for
    each (num_clips of them, 1 to 20). With segments, Luna cuts exactly those
    ranges, for example [{"start_time": "01:05", "end_time": "01:40"}].
    Poll job_status with the returned job_id.
    """
    body: Dict[str, Any] = {
        "url": url,
        "action": "manual_clip" if segments else "ai_clip",
        "num_clips": num_clips,
        "aspect_ratio": aspect_ratio,
        "use_face_detect": use_face_detect,
    }
    if segments:
        body["segments"] = segments
    if workspace_name:
        body["workspace_name"] = workspace_name
    job = await _api("POST", "/api/process", body)
    return {**job, "next": "Call job_status every 15 to 30 seconds until it finishes."}


@mcp.tool(annotations=READ_ONLY)
async def job_status(job_id: str) -> Dict[str, Any]:
    """Return a job's status (queued, running stages, completed, failed, cancelled), progress and error."""
    job = await _api("GET", f"/api/status/{_job_path(job_id)}")
    return {
        "job_id": job.get("id", job_id),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "stage_detail": job.get("stage_detail"),
        "progress": job.get("progress"),
        "finished": job.get("status") in FINISHED,
        "clip_count": len(job.get("results") or []),
        "error": job.get("error"),
        "retryable": job.get("retryable", False),
        "recent_logs": (job.get("logs") or [])[-5:],
    }


def _download(url: str, dest: str) -> None:
    try:
        with urllib.request.urlopen(url, timeout=300) as res, open(dest, "wb") as f:
            while chunk := res.read(1 << 20):
                f.write(chunk)
    except urllib.error.URLError as e:
        raise ToolError(f"Could not download {os.path.basename(dest)}: {getattr(e, 'reason', e)}") from None


@mcp.tool(annotations=ToolAnnotations(open_world_hint=False))
async def get_clips(job_id: str, save_to: Optional[str] = None) -> Dict[str, Any]:
    """List the clips of a completed job: title, time range, score, caption and download URL.

    With save_to (a local folder, created if missing) each clip is also downloaded
    there and its local path returned. Use it when Luna runs on another machine.
    """
    job = await _api("GET", f"/api/status/{_job_path(job_id)}")
    if job.get("status") != "completed":
        raise ToolError(f"Job {job_id} is {job.get('status')}, not completed. Check job_status first.")
    clips = []
    for item in job.get("results") or []:
        clip = {k: item.get(k) for k in ("title", "start_time", "end_time", "score", "caption", "filename")}
        clip["download_url"] = luna_url() + item["download_url"] if item.get("download_url") else None
        clips.append({k: v for k, v in clip.items() if v is not None})
    if save_to:
        folder = os.path.abspath(os.path.expanduser(save_to))
        os.makedirs(folder, exist_ok=True)
        for clip in clips:
            if clip.get("download_url") and clip.get("filename"):
                # basename: the name comes from the server and must not leave the folder.
                dest = os.path.join(folder, os.path.basename(clip["filename"]))
                await asyncio.to_thread(_download, clip["download_url"], dest)
                clip["local_path"] = dest
    return {"job_id": job_id, "project_id": job.get("project_id"), "clips": clips}


@mcp.tool(annotations=ToolAnnotations(open_world_hint=True))
async def retry_job(job_id: str) -> Dict[str, Any]:
    """Run a failed job again with the same settings. Downloads already finished are reused."""
    return await _api("POST", f"/api/retry/{_job_path(job_id)}")


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True, open_world_hint=False))
async def cancel_job(job_id: str) -> Dict[str, Any]:
    """Stop a running job. Its partial files are deleted; a finished job is left alone."""
    return await _api("POST", f"/api/cancel/{_job_path(job_id)}")


@mcp.tool(annotations=READ_ONLY)
async def list_projects() -> Dict[str, Any]:
    """List the workspaces in Luna's media vault, newest first, with their files."""
    data = await _api("GET", "/api/vault/projects")
    return {"projects": data.get("projects", []), "stats": data.get("stats")}


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
