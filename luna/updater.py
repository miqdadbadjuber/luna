# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

"""Cross-platform in-app updater (Windows, macOS, Linux) for Git and archive installs."""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from .__version__ import __version__ as APP_VERSION

DEFAULT_REPO_URL = "https://github.com/miqdadbadjuber/luna"
DEFAULT_BRANCH = "main"
VERSION_MARKER_FILENAME = ".luna-version"
RELEASE_CACHE_TTL_SECONDS = 3600

# Never overwrite user secrets, virtualenvs, cookies, media workspaces, or git state on archive updates.
PRESERVED_TOP_LEVEL = frozenset({
    ".env",
    ".venv",
    ".git",
    "cookies.txt",
    "output",
    "media",
    "media-vault",
    "__pycache__",
    "issue",
    "skills",
})

_GITHUB_REPO_RE = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?/?$", re.IGNORECASE)
_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?$")
_SAFE_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")

_release_cache_lock = threading.Lock()
_release_cache: Dict[str, Dict] = {}


def parse_semver(raw: Optional[str]) -> Optional[Tuple[int, int, int]]:
    if not raw:
        return None
    m = _SEMVER_RE.match(str(raw).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def normalize_version(raw: Optional[str]) -> str:
    parsed = parse_semver(raw)
    if not parsed:
        return ""
    return f"v{parsed[0]}.{parsed[1]}.{parsed[2]}"


def is_newer_version(latest: Optional[str], current: Optional[str]) -> bool:
    p_latest = parse_semver(latest)
    p_current = parse_semver(current)
    if not p_latest or not p_current:
        return False
    return p_latest > p_current


def get_app_version(base_dir: Optional[str] = None) -> str:
    """Return the installed Luna release version in vX.Y.Z format."""
    if base_dir:
        root = Path(base_dir)
        version_file = root / "luna" / "__version__.py"
        if version_file.is_file():
            try:
                text = version_file.read_text(encoding="utf-8")
                m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
                if m:
                    norm = normalize_version(m.group(1))
                    if norm:
                        return norm
            except Exception:
                pass
        marker = root / VERSION_MARKER_FILENAME
        if marker.is_file():
            try:
                first_line = marker.read_text(encoding="utf-8").strip().splitlines()[0].strip()
                norm = normalize_version(first_line)
                if norm:
                    return norm
            except Exception:
                pass
    return normalize_version(APP_VERSION) or "v1.0.0"


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
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    return subprocess.run(
        ["git", "-C", base_dir, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
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


def fetch_latest_release(
    repo_url: Optional[str] = None,
    timeout: float = 12.0,
    use_cache: bool = False,
) -> Optional[Dict[str, str]]:
    """Fetch latest published GitHub Release metadata using ETag + optional TTL cache."""
    resolved_url = (repo_url or _repo_url()).rstrip("/")
    owner, repo = _parse_github_owner_repo(resolved_url)
    cache_key = f"{owner.lower()}/{repo.lower()}"
    now = time.monotonic()

    cached_etag = ""
    cached_data: Optional[Dict[str, str]] = None
    with _release_cache_lock:
        entry = _release_cache.get(cache_key)
        if entry:
            cached_etag = str(entry.get("etag") or "")
            cached_data = entry.get("data")
            if use_cache and (now - float(entry.get("ts") or 0.0)) < RELEASE_CACHE_TTL_SECONDS:
                return dict(cached_data) if isinstance(cached_data, dict) else None

    api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Luna-Updater",
    }
    if cached_etag:
        headers["If-None-Match"] = cached_etag

    req = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            new_etag = str(resp.headers.get("ETag") or "").strip()
    except urllib.error.HTTPError as e:
        if e.code == 304 and isinstance(cached_data, dict):
            with _release_cache_lock:
                _release_cache[cache_key] = {
                    "ts": now,
                    "etag": cached_etag,
                    "data": dict(cached_data),
                }
            return dict(cached_data)
        if e.code == 404:
            with _release_cache_lock:
                _release_cache[cache_key] = {"ts": now, "etag": "", "data": None}
            return None
        raise RuntimeError(f"GitHub update check failed (HTTP {e.code}).") from e
    except Exception as e:
        raise RuntimeError(f"Could not reach GitHub to check for updates: {e}") from e

    tag_name = str(payload.get("tag_name") or "").strip()
    norm_version = normalize_version(tag_name)
    if not norm_version:
        return None

    release_title = str(payload.get("name") or "").strip() or norm_version
    release_notes = str(payload.get("body") or "").strip()
    published_at = str(payload.get("published_at") or payload.get("created_at") or "").strip()
    release_url = str(payload.get("html_url") or f"{resolved_url}/releases/tag/{tag_name}").strip()

    result = {
        "tag_name": tag_name,
        "version": norm_version,
        "title": release_title,
        "notes": release_notes,
        "published_at": published_at,
        "url": release_url,
    }
    with _release_cache_lock:
        _release_cache[cache_key] = {
            "ts": now,
            "etag": new_etag,
            "data": dict(result),
        }
    return result


def check_for_updates(
    base_dir: str,
    repo_url: Optional[str] = None,
    ref: Optional[str] = None,
    use_cache: bool = False,
) -> Dict:
    """Compare local install version against the latest GitHub Release (with commit fallback)."""
    local_sha, install_mode = get_local_version(base_dir)
    release = fetch_latest_release(repo_url=repo_url, use_cache=use_cache)

    if release and release.get("version"):
        current_version = get_app_version(base_dir)
        latest_version = release["version"]
        p_cur = parse_semver(current_version)
        p_lat = parse_semver(latest_version)

        if p_lat and p_cur and p_lat > p_cur:
            update_available = True
            reason = "new_release"
        elif p_lat and p_cur and p_cur > p_lat:
            update_available = False
            reason = "local_ahead"
        else:
            update_available = False
            reason = "up_to_date"

        return {
            "update_available": update_available,
            "reason": reason,
            "source": "release",
            "install_mode": install_mode,
            "current_version": current_version,
            "latest_version": latest_version,
            "target_tag": release["tag_name"],
            "release_title": release["title"],
            "release_notes": release["notes"],
            "release_url": release["url"],
            "current_sha": local_sha or "",
            "current_short_sha": current_version,
            "latest_sha": "",
            "latest_short_sha": latest_version,
            "latest_message": release["title"],
            "latest_date": release["published_at"],
            "commit_url": release["url"],
        }

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
        "source": "commit",
        "install_mode": install_mode,
        "current_version": get_app_version(base_dir),
        "latest_version": "",
        "target_tag": "",
        "release_title": remote["message"],
        "release_notes": "",
        "release_url": remote["url"],
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


def _find_uv_binary() -> Optional[str]:
    found = shutil.which("uv")
    if found:
        return found
    exe_name = "uv.exe" if sys.platform == "win32" else "uv"
    candidates = [
        Path.home() / ".local" / "bin" / exe_name,
        Path.home() / ".cargo" / "bin" / exe_name,
        Path(sys.executable).resolve().parent / exe_name,
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def _install_requirements(base_dir: str) -> None:
    req_file = Path(base_dir) / "requirements.txt"
    if not req_file.is_file():
        return
    uv_bin = _find_uv_binary()
    if uv_bin:
        cmd = [uv_bin, "pip", "install", "--python", sys.executable, "-r", str(req_file)]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--no-input", "-r", str(req_file)]
    try:
        res = subprocess.run(cmd, cwd=base_dir, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Installing updated dependencies timed out after 2 minutes. "
            "Check your network connection and retry."
        ) from exc
    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip()[-600:]
        raise RuntimeError(f"Failed to install updated dependencies: {tail or 'unknown error'}")


def _safe_extract_zip(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """Extract a ZIP archive while blocking Zip Slip path traversal and symlinks."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_root = dest_dir.resolve()
    for member in zf.infolist():
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise RuntimeError(f"Unsafe symlink in update archive: {member.filename}")
        raw_name = member.filename
        if not raw_name or raw_name.startswith(("/", "\\")):
            raise RuntimeError(f"Unsafe absolute path in update archive: {raw_name}")
        norm_parts = Path(raw_name.replace("\\", "/")).parts
        if any(part in ("..", "") or ":" in part for part in norm_parts):
            raise RuntimeError(f"Unsafe path traversal in update archive: {raw_name}")
        target = (dest_root / Path(*norm_parts)).resolve()
        if os.path.commonpath([str(dest_root), str(target)]) != str(dest_root):
            raise RuntimeError(f"Update archive entry escapes target directory: {raw_name}")
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def _apply_archive_update(
    base_dir: str,
    repo_url: str,
    ref: str,
    target_marker: str,
    *,
    is_tag: bool = False,
    on_stage: Optional[Callable[[str, str], None]] = None,
    read_timeout: float = 20.0,
    total_timeout: float = 90.0,
    max_attempts: int = 2,
) -> None:
    ref_kind = "tags" if is_tag else "heads"
    archive_url = f"{repo_url.rstrip('/')}/archive/refs/{ref_kind}/{ref}.zip"
    label = f"Luna {ref}" if is_tag else "latest update"
    root = Path(base_dir)
    with tempfile.TemporaryDirectory(prefix="luna_update_") as tmp:
        zip_path = Path(tmp) / "luna-update.zip"
        last_err: Optional[Exception] = None
        attempts = max(1, int(max_attempts))
        for attempt in range(1, attempts + 1):
            if attempt > 1 and on_stage:
                on_stage("downloading", f"Retrying download for {label}...")
            req = urllib.request.Request(archive_url, headers={"User-Agent": "Luna-Updater"})
            deadline = time.monotonic() + max(5.0, float(total_timeout))
            try:
                with urllib.request.urlopen(req, timeout=read_timeout) as resp, zip_path.open("wb") as out:
                    headers = getattr(resp, "headers", None)
                    raw_len = headers.get("Content-Length") if headers and hasattr(headers, "get") else None
                    try:
                        total_bytes = int(raw_len) if raw_len else 0
                    except (TypeError, ValueError):
                        total_bytes = 0

                    downloaded = 0
                    last_report_ts = 0.0
                    last_report_bytes = 0
                    while True:
                        if time.monotonic() > deadline:
                            raise TimeoutError(f"Download exceeded {int(total_timeout)}s limit")
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        now = time.monotonic()
                        if on_stage and (now - last_report_ts >= 0.35 or downloaded - last_report_bytes >= 262144):
                            last_report_ts = now
                            last_report_bytes = downloaded
                            mb_done = downloaded / (1024 * 1024)
                            if total_bytes > 0:
                                pct = min(99, int((downloaded * 100) / total_bytes))
                                mb_total = total_bytes / (1024 * 1024)
                                on_stage("downloading", f"Downloading {label} ({pct}% - {mb_done:.1f} / {mb_total:.1f} MB)...")
                            else:
                                on_stage("downloading", f"Downloading {label} ({mb_done:.1f} MB)...")
                last_err = None
                break
            except Exception as e:
                last_err = e
                if attempt < attempts:
                    time.sleep(0.6)
                    continue
        if last_err is not None:
            raise RuntimeError(f"Could not download update archive: {last_err}") from last_err

        if on_stage:
            on_stage("extracting", "Extracting update files...")
        extract_dir = Path(tmp) / "extracted"
        with zipfile.ZipFile(zip_path, "r") as zf:
            _safe_extract_zip(zf, extract_dir)

        entries = [p for p in extract_dir.iterdir() if p.is_dir()]
        if not entries:
            raise RuntimeError("Update archive was empty.")
        src_root = entries[0]

        if on_stage:
            on_stage("applying", f"Applying {label}...")
        for item in src_root.iterdir():
            if item.name in PRESERVED_TOP_LEVEL:
                continue
            dst = root / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)

    if target_marker:
        _write_version_marker(base_dir, target_marker)


def apply_update(
    base_dir: str,
    *,
    target_sha: Optional[str] = None,
    target_tag: Optional[str] = None,
    repo_url: Optional[str] = None,
    ref: Optional[str] = None,
    on_stage: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, str]:
    """Download and apply a Luna release tag (or branch fallback) across Git or archive installs."""
    resolved_url = (repo_url or _repo_url()).rstrip("/")
    resolved_ref = ref or _repo_ref()
    clean_tag = str(target_tag or "").strip()
    if clean_tag and not _SAFE_TAG_RE.match(clean_tag):
        raise RuntimeError(f"Invalid release tag: {clean_tag}")

    req_path = Path(base_dir) / "requirements.txt"
    req_before = _file_sha256(req_path)

    _, install_mode = get_local_version(base_dir)
    if on_stage:
        on_stage("downloading", f"Downloading Luna {clean_tag}..." if clean_tag else "Downloading latest update...")

    if install_mode == "git":
        status = _run_git(base_dir, "status", "--porcelain", "--untracked-files=no", timeout=15.0)
        if status.returncode == 0 and status.stdout.strip():
            raise RuntimeError(
                "Local code changes were detected in this Git checkout. "
                "Commit or stash them before running an in-app update."
            )
        try:
            if clean_tag:
                fetch = _run_git(base_dir, "fetch", "--tags", "origin", timeout=45.0)
                if fetch.returncode != 0:
                    err = (fetch.stderr or fetch.stdout or "").strip()[-400:]
                    raise RuntimeError(f"Git tag fetch failed: {err or 'fetch --tags returned non-zero'}")
                if on_stage:
                    on_stage("applying", f"Applying Luna {clean_tag}...")
                merge = _run_git(base_dir, "merge", "--ff-only", clean_tag, timeout=30.0)
                if merge.returncode != 0:
                    err = (merge.stderr or merge.stdout or "").strip()[-400:]
                    raise RuntimeError(f"Git update to {clean_tag} failed: {err or 'merge --ff-only returned non-zero'}")
            else:
                pull = _run_git(base_dir, "pull", "--ff-only", "origin", resolved_ref, timeout=45.0)
                if pull.returncode != 0:
                    err = (pull.stderr or pull.stdout or "").strip()[-400:]
                    raise RuntimeError(f"Git update failed: {err or 'pull --ff-only returned non-zero'}")
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Git update timed out while contacting GitHub. Check your internet connection and try again."
            ) from exc
        new_sha, _ = get_local_version(base_dir)
    else:
        if clean_tag:
            _apply_archive_update(
                base_dir, resolved_url, clean_tag, clean_tag, is_tag=True, on_stage=on_stage
            )
            new_sha = clean_tag
        else:
            sha_to_record = target_sha
            if not sha_to_record:
                sha_to_record = fetch_remote_latest(repo_url=resolved_url, ref=resolved_ref)["sha"]
            _apply_archive_update(
                base_dir, resolved_url, resolved_ref, sha_to_record, is_tag=False, on_stage=on_stage
            )
            new_sha = sha_to_record

    req_after = _file_sha256(req_path)
    if req_after and req_after != req_before:
        if on_stage:
            on_stage("dependencies", "Installing updated dependencies...")
        _install_requirements(base_dir)

    updated_version = clean_tag or get_app_version(base_dir)
    return {
        "install_mode": install_mode,
        "updated_version": updated_version,
        "updated_sha": new_sha or "",
        "updated_short_sha": clean_tag or (new_sha[:7] if new_sha else ""),
    }


RESTART_EXIT_CODE = 42


def schedule_server_restart(base_dir: str, delay_sec: float = 1.4) -> None:
    """Restart Luna cleanly in the same terminal when supervised, or via fallback helper otherwise."""
    port = os.getenv("LUNA_PORT", "8000").strip() or "8000"
    pid = os.getpid()
    supervised = os.getenv("LUNA_SUPERVISED", "").strip() == "1"

    if supervised:
        def _exit_for_supervisor() -> None:
            import time as _time
            _time.sleep(max(0.4, delay_sec))
            print(f"[updater] Update applied. Restarting Luna in place (pid={pid}, port={port})...", flush=True)
            os._exit(RESTART_EXIT_CODE)

        import threading
        threading.Thread(target=_exit_for_supervisor, daemon=True).start()
        return

    wait_before_probe = max(1.6, delay_sec + 0.5)
    helper = (
        "import os, socket, subprocess, sys, time\n"
        f"port = int({port!r})\n"
        f"base_dir = {base_dir!r}\n"
        f"time.sleep({wait_before_probe!r})\n"
        "for _ in range(40):\n"
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
        "    kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)\n"
        "else:\n"
        "    kwargs['start_new_session'] = True\n"
        "subprocess.Popen([sys.executable, '-m', 'luna.start'], **kwargs)\n"
    )

    spawn_kwargs: Dict = {"cwd": base_dir}
    if sys.platform == "win32":
        spawn_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
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
