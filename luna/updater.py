# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

"""Cross-platform in-app updater (Windows, macOS, Linux) for Git and archive installs."""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

DEFAULT_REPO_URL = "https://github.com/miqdadbadjuber/luna"
DEFAULT_BRANCH = "main"
VERSION_MARKER_FILENAME = ".luna-version"

# Never overwrite user secrets, virtualenvs, cookies, media workspaces, or git state on archive updates.
PRESERVED_TOP_LEVEL = frozenset({
    ".env",
    ".venv",
    ".git",
    "cookies.txt",
    "output",
    "media",
    "__pycache__",
    "issue",
})

_GITHUB_REPO_RE = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?/?$", re.IGNORECASE)


def _repo_url() -> str:
    return (os.getenv("LUNA_REPO_URL") or DEFAULT_REPO_URL).strip().rstrip("/")


def _repo_ref() -> str:
    return (os.getenv("LUNA_REF") or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH


def _parse_github_owner_repo(repo_url: str) -> Tuple[str, str]:
    match = _GITHUB_REPO_RE.search(repo_url.strip())
    if not match:
        raise RuntimeError(f"Unsupported repository URL for updates: {repo_url}")
    return match.group("owner"), match.group("repo")


def _run_git(base_dir: str, *args: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", base_dir, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def get_local_version(base_dir: str) -> Tuple[Optional[str], str]:
    """Return (sha_or_none, install_mode) where install_mode is 'git' or 'archive'."""
    root = Path(base_dir)
    if (root / ".git").exists() and shutil.which("git"):
        try:
            res = _run_git(base_dir, "rev-parse", "HEAD", timeout=10.0)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip(), "git"
        except Exception:
            pass
        return None, "git"

    marker = root / VERSION_MARKER_FILENAME
    if marker.is_file():
        try:
            sha = marker.read_text(encoding="utf-8").strip().splitlines()[0].strip()
            if sha:
                return sha, "archive"
        except Exception:
            pass
    return None, "archive"


def _write_version_marker(base_dir: str, sha: str) -> None:
    if not sha:
        return
    marker = Path(base_dir) / VERSION_MARKER_FILENAME
    marker.write_text(f"{sha.strip()}\n", encoding="utf-8")


def fetch_remote_latest(
    repo_url: Optional[str] = None,
    ref: Optional[str] = None,
    timeout: float = 12.0,
) -> Dict[str, str]:
    """Fetch latest commit metadata for `ref` from the GitHub API."""
    import json

    resolved_url = (repo_url or _repo_url()).rstrip("/")
    resolved_ref = ref or _repo_ref()
    owner, repo = _parse_github_owner_repo(resolved_url)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{resolved_ref}"
    req = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Luna-Updater",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub update check failed (HTTP {e.code}).") from e
    except Exception as e:
        raise RuntimeError(f"Could not reach GitHub to check for updates: {e}") from e

    sha = str(payload.get("sha") or "").strip()
    if not sha:
        raise RuntimeError("GitHub did not return a valid commit SHA.")
    commit_obj = payload.get("commit") or {}
    raw_msg = str(commit_obj.get("message") or "").strip()
    first_line = raw_msg.splitlines()[0].strip() if raw_msg else "Latest update"
    date = str((commit_obj.get("committer") or commit_obj.get("author") or {}).get("date") or "")
    return {
        "sha": sha,
        "short_sha": sha[:7],
        "message": first_line,
        "date": date,
        "url": str(payload.get("html_url") or f"{resolved_url}/commit/{sha}"),
    }


def _git_is_ancestor(base_dir: str, ancestor_sha: str) -> bool:
    """True when `ancestor_sha` is already contained in local HEAD (e.g. unpushed dev commits)."""
    try:
        res = _run_git(base_dir, "merge-base", "--is-ancestor", ancestor_sha, "HEAD", timeout=10.0)
        return res.returncode == 0
    except Exception:
        return False


def check_for_updates(
    base_dir: str,
    repo_url: Optional[str] = None,
    ref: Optional[str] = None,
) -> Dict:
    """Compare local install version against GitHub `main` and return update availability."""
    local_sha, install_mode = get_local_version(base_dir)
    remote = fetch_remote_latest(repo_url=repo_url, ref=ref)
    remote_sha = remote["sha"]

    if local_sha and local_sha == remote_sha:
        update_available = False
        reason = "up_to_date"
    elif local_sha and install_mode == "git" and _git_is_ancestor(base_dir, remote_sha):
        update_available = False
        reason = "local_ahead"
    elif not local_sha:
        update_available = True
        reason = "untracked_install"
    else:
        update_available = True
        reason = "behind_remote"

    return {
        "update_available": update_available,
        "reason": reason,
        "install_mode": install_mode,
        "current_sha": local_sha or "",
        "current_short_sha": (local_sha[:7] if local_sha else ""),
        "latest_sha": remote_sha,
        "latest_short_sha": remote["short_sha"],
        "latest_message": remote["message"],
        "latest_date": remote["date"],
        "commit_url": remote["url"],
    }


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _install_requirements(base_dir: str) -> None:
    req_file = Path(base_dir) / "requirements.txt"
    if not req_file.is_file():
        return
    uv_bin = shutil.which("uv")
    if uv_bin:
        cmd = [uv_bin, "pip", "install", "--python", sys.executable, "-r", str(req_file)]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file)]
    res = subprocess.run(cmd, cwd=base_dir, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip()[-600:]
        raise RuntimeError(f"Failed to install updated dependencies: {tail or 'unknown error'}")


def _apply_archive_update(base_dir: str, repo_url: str, ref: str, target_sha: str) -> None:
    archive_url = f"{repo_url.rstrip('/')}/archive/refs/heads/{ref}.zip"
    root = Path(base_dir)
    with tempfile.TemporaryDirectory(prefix="luna_update_") as tmp:
        zip_path = Path(tmp) / "luna-update.zip"
        req = urllib.request.Request(archive_url, headers={"User-Agent": "Luna-Updater"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp, zip_path.open("wb") as out:
                shutil.copyfileobj(resp, out)
        except Exception as e:
            raise RuntimeError(f"Could not download update archive: {e}") from e

        extract_dir = Path(tmp) / "extracted"
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        entries = [p for p in extract_dir.iterdir() if p.is_dir()]
        if not entries:
            raise RuntimeError("Update archive was empty.")
        src_root = entries[0]

        for item in src_root.iterdir():
            if item.name in PRESERVED_TOP_LEVEL:
                continue
            dst = root / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)

    if target_sha:
        _write_version_marker(base_dir, target_sha)


def apply_update(
    base_dir: str,
    *,
    target_sha: Optional[str] = None,
    repo_url: Optional[str] = None,
    ref: Optional[str] = None,
    on_stage: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, str]:
    """Download and apply the latest Luna update across Git or archive installs."""
    resolved_url = (repo_url or _repo_url()).rstrip("/")
    resolved_ref = ref or _repo_ref()
    req_path = Path(base_dir) / "requirements.txt"
    req_before = _file_sha256(req_path)

    _, install_mode = get_local_version(base_dir)
    if on_stage:
        on_stage("downloading", "Downloading latest update...")

    if install_mode == "git":
        status = _run_git(base_dir, "status", "--porcelain", "--untracked-files=no", timeout=15.0)
        if status.returncode == 0 and status.stdout.strip():
            raise RuntimeError(
                "Local code changes were detected in this Git checkout. "
                "Commit or stash them before running an in-app update."
            )
        pull = _run_git(base_dir, "pull", "--ff-only", "origin", resolved_ref, timeout=90.0)
        if pull.returncode != 0:
            err = (pull.stderr or pull.stdout or "").strip()[-400:]
            raise RuntimeError(f"Git update failed: {err or 'pull --ff-only returned non-zero'}")
        new_sha, _ = get_local_version(base_dir)
    else:
        sha_to_record = target_sha
        if not sha_to_record:
            sha_to_record = fetch_remote_latest(repo_url=resolved_url, ref=resolved_ref)["sha"]
        _apply_archive_update(base_dir, resolved_url, resolved_ref, sha_to_record)
        new_sha = sha_to_record

    req_after = _file_sha256(req_path)
    if req_after and req_after != req_before:
        if on_stage:
            on_stage("dependencies", "Installing updated dependencies...")
        _install_requirements(base_dir)

    return {
        "install_mode": install_mode,
        "updated_sha": new_sha or "",
        "updated_short_sha": (new_sha[:7] if new_sha else ""),
    }


def schedule_server_restart(base_dir: str, delay_sec: float = 1.4) -> None:
    """Spawn a detached cross-platform helper that restarts Luna on the same port after exit."""
    port = os.getenv("LUNA_PORT", "8000").strip() or "8000"
    pid = os.getpid()
    helper = (
        "import os, socket, subprocess, sys, time\n"
        f"port = int({port!r})\n"
        f"base_dir = {base_dir!r}\n"
        "time.sleep(1.2)\n"
        "for _ in range(30):\n"
        "    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:\n"
        "        s.settimeout(0.3)\n"
        "        if s.connect_ex(('127.0.0.1', port)) != 0:\n"
        "            break\n"
        "    time.sleep(0.25)\n"
        "env = dict(os.environ)\n"
        "env['LUNA_PORT'] = str(port)\n"
        "env['LUNA_NO_BROWSER'] = '1'\n"
        "kwargs = {'cwd': base_dir, 'env': env}\n"
        "if sys.platform == 'win32':\n"
        "    kwargs['creationflags'] = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)\n"
        "else:\n"
        "    kwargs['start_new_session'] = True\n"
        "subprocess.Popen([sys.executable, '-m', 'luna.start'], **kwargs)\n"
    )

    spawn_kwargs: Dict = {"cwd": base_dir}
    if sys.platform == "win32":
        spawn_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        spawn_kwargs["start_new_session"] = True

    subprocess.Popen([sys.executable, "-c", helper], **spawn_kwargs)

    def _exit_soon() -> None:
        import time as _time
        _time.sleep(max(0.4, delay_sec))
        print(f"[updater] Restarting Luna (pid={pid}, port={port})...", flush=True)
        os._exit(0)

    import threading
    threading.Thread(target=_exit_soon, daemon=True).start()
