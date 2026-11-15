# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

import gc
import hashlib
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional

import re
import uuid

from . import storage_manager

INDEX_FILE_NAME = "meta.json"


def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON through a temp file in the same directory, then replace atomically.

    A crash or a full disk can no longer leave a truncated meta.json behind, which
    used to be read back as "empty" and then overwritten with a single record.
    """
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass



def _is_inside_storage(path: str, root: str) -> bool:
    """True only for an entry strictly inside the storage root (not the root itself)."""
    try:
        root_real = os.path.realpath(os.path.abspath(root))
        path_real = os.path.realpath(os.path.abspath(path))
        if path_real == root_real:
            return False
        return os.path.commonpath([root_real, path_real]) == root_real
    except (TypeError, ValueError):
        return False


def _generate_folder_project_id(folder_path: str) -> str:
    """Generate a deterministic project ID for legacy folders.

    Keyed on the path relative to the storage root, so moving the vault to another
    disk keeps the IDs stable (an absolute-path hash changed on every migration).
    """
    root = storage_manager.get_storage_root()
    try:
        rel = os.path.relpath(os.path.abspath(folder_path), os.path.abspath(root))
    except ValueError:
        rel = os.path.abspath(folder_path)
    norm = rel.replace("\\", "/").lower()
    return f"proj_leg_{hashlib.md5(norm.encode('utf-8')).hexdigest()[:8]}"


def _extract_saved_at(item: Dict[str, Any]) -> float:
    """Safely extract saved_at or created_at timestamp as float for sorting."""
    val = item.get("saved_at") or item.get("created_at")
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            pass
    return 0.0


def save_project_metadata(target_dir: str, project_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save or update a project record in target directory's meta.json.
    """
    if not os.path.isabs(target_dir):
        target_dir = os.path.join(storage_manager.get_storage_root(), target_dir)
    os.makedirs(target_dir, exist_ok=True)

    if not project_data.get("created_at"):
        project_data["created_at"] = time.time()
    if not project_data.get("project_id"):
        project_data["project_id"] = f"proj_{uuid.uuid4().hex[:8]}"

    meta_path = os.path.join(target_dir, INDEX_FILE_NAME)
    current_entries: List[Dict[str, Any]] = []

    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    current_entries = [it for it in loaded if isinstance(it, dict)]
                elif isinstance(loaded, dict):
                    current_entries = [loaded]
        except Exception:
            current_entries = []

    proj_id = project_data.get("project_id")
    updated = False
    for idx, existing in enumerate(current_entries):
        if proj_id and existing.get("project_id") == proj_id:
            current_entries[idx] = project_data
            updated = True
            break

    if not updated:
        current_entries.append(project_data)

    _atomic_write_json(meta_path, current_entries)

    return project_data


def list_vault_projects() -> List[Dict[str, Any]]:
    """Scan storage root for all projects, sorted by created_at descending.

    Read-only by contract: it never writes meta.json. Legacy flat records are grouped
    into a virtual project in memory and flagged with ``virtual: true`` so the UI can
    hide destructive actions (deleting the syntetic category project would delete
    every loose file in that category).
    """
    root = storage_manager.get_storage_root()
    category_roots = {os.path.abspath(p) for p in storage_manager.category_root_paths().values()}
    projects: List[Dict[str, Any]] = []

    if not os.path.exists(root):
        return projects

    for current_dir, _, files in os.walk(root):
        if INDEX_FILE_NAME not in files:
            continue
        meta_path = os.path.join(current_dir, INDEX_FILE_NAME)
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        entries: List[Dict[str, Any]] = []
        if isinstance(data, list):
            entries = [e for e in data if isinstance(e, dict)]
        elif isinstance(data, dict):
            entries = [data]

        legacy_files: List[Dict[str, Any]] = []
        for entry in entries:
            if entry.get("project_id"):
                projects.append(entry)
            elif entry.get("filename") or entry.get("file_path"):
                legacy_files.append(entry)

        if legacy_files:
            dir_name = os.path.basename(current_dir)
            first = legacy_files[0]
            is_category_root = os.path.abspath(current_dir) in category_roots
            projects.append({
                "project_id": _generate_folder_project_id(current_dir),
                "workspace_name": f"{dir_name} Archive" if is_category_root else dir_name,
                "platform": first.get("platform", "youtube"),
                "action": first.get("action", "type_yt_video"),
                "source_title": first.get("title", dir_name),
                "created_at": _extract_saved_at(first),
                "folder_path": current_dir,
                "files": legacy_files,
                "virtual": True,
            })

    projects.sort(key=_extract_saved_at, reverse=True)
    return projects


def rename_vault_project(project_id: str, new_name: str) -> bool:
    """
    Rename a project's workspace_name in its meta.json.
    Supports both structured project records and legacy folder projects.
    """
    root = storage_manager.get_storage_root()
    clean_name = new_name.strip()
    if not clean_name or not os.path.exists(root):
        return False

    # Pass 1: Exact match by project_id
    for current_dir, _, files in os.walk(root):
        if INDEX_FILE_NAME in files:
            meta_path = os.path.join(current_dir, INDEX_FILE_NAME)
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            entries = data if isinstance(data, list) else [data]
            modified = False
            for entry in entries:
                if isinstance(entry, dict) and entry.get("project_id") == project_id:
                    entry["workspace_name"] = clean_name
                    modified = True
                    break

            if modified:
                try:
                    _atomic_write_json(meta_path, entries)
                    return True
                except Exception:
                    pass

    # Pass 2: Fallback for legacy virtual project IDs (e.g. proj_leg_995082 or folder match)
    for current_dir, _, files in os.walk(root):
        if INDEX_FILE_NAME in files:
            meta_path = os.path.join(current_dir, INDEX_FILE_NAME)
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            entries = data if isinstance(data, list) else [data]
            matches_legacy = project_id == _generate_folder_project_id(current_dir)

            if matches_legacy:
                updated = False
                for entry in entries:
                    if isinstance(entry, dict) and (entry.get("project_id") or "files" in entry):
                        entry["workspace_name"] = clean_name
                        entry["project_id"] = project_id
                        updated = True
                        break

                if not updated:
                    dir_name = os.path.basename(current_dir)
                    legacy_files = [e for e in entries if isinstance(e, dict)]
                    first = legacy_files[0] if legacy_files else {}
                    proj_record = {
                        "project_id": project_id,
                        "workspace_name": clean_name,
                        "platform": first.get("platform", "youtube"),
                        "action": first.get("action", "type_yt_video"),
                        "source_title": first.get("title", dir_name),
                        "created_at": _extract_saved_at(first) or time.time(),
                        "folder_path": current_dir,
                        "files": legacy_files,
                    }
                    entries = [proj_record]

                try:
                    _atomic_write_json(meta_path, entries)
                    return True
                except Exception:
                    pass

    return False


def _safe_remove_path(filepath: str, max_retries: int = 3, delay: float = 0.15) -> bool:
    """Safely remove a file or directory with retry on Windows file lock (PermissionError)."""
    if not filepath or not os.path.exists(filepath):
        return True
    import gc
    for _ in range(max_retries):
        try:
            if os.path.isfile(filepath):
                os.remove(filepath)
            elif os.path.isdir(filepath):
                shutil.rmtree(filepath)
            return True
        except PermissionError:
            gc.collect()
            time.sleep(delay)
        except Exception:
            break
    return not os.path.exists(filepath)


def delete_vault_project(project_id: str) -> str:
    """Delete a project by ID and clean up its folder.

    Returns "deleted", "locked" (a file is still open elsewhere) or "not_found".
    Category roots are never treated as projects: deleting one used to wipe every
    loose file in that category.
    """
    root = storage_manager.get_storage_root()
    if not os.path.exists(root):
        return "not_found"
    category_roots = {os.path.abspath(p) for p in storage_manager.category_root_paths().values()}

    for current_dir, _, files in os.walk(root):
        if INDEX_FILE_NAME not in files:
            continue
        meta_path = os.path.join(current_dir, INDEX_FILE_NAME)
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        entries = data if isinstance(data, list) else [data]
        target_proj = None
        remaining_entries = []

        for entry in entries:
            if isinstance(entry, dict) and entry.get("project_id") == project_id:
                target_proj = entry
            else:
                remaining_entries.append(entry)

        # Legacy folder project (no project_id stored on disk).
        if target_proj is None and project_id == _generate_folder_project_id(current_dir):
            target_proj = {
                "project_id": project_id,
                "workspace_name": os.path.basename(current_dir),
                "folder_path": current_dir,
                "files": [e for e in entries if isinstance(e, dict)],
            }
            remaining_entries = []

        if target_proj is None:
            continue

        if os.path.abspath(current_dir) in category_roots:
            return "not_found"

        locked = False
        for f in target_proj.get("files", []):
            if not isinstance(f, dict):
                continue
            fp = f.get("file_path")
            if not fp or not _is_inside_storage(fp, root):
                continue
            # Only ever unlink regular files; a metadata path must not rmtree a tree.
            if os.path.isfile(fp) and not _safe_remove_path(fp):
                locked = True

        if locked:
            return "locked"

        proj_folder = target_proj.get("folder_path")
        if (
            proj_folder
            and _is_inside_storage(proj_folder, root)
            and os.path.abspath(proj_folder) == os.path.abspath(current_dir)
            and os.path.abspath(proj_folder) not in category_roots
            and not remaining_entries
        ):
            # Nothing else is recorded in this folder, so it belongs to the project.
            if not _safe_remove_path(proj_folder):
                return "locked"
            return "deleted"

        if remaining_entries:
            try:
                _atomic_write_json(meta_path, remaining_entries)
            except Exception:
                return "locked"
        else:
            try:
                if os.path.exists(meta_path):
                    os.remove(meta_path)
            except Exception:
                return "locked"
        return "deleted"

    return "not_found"


def get_next_workspace_index() -> int:
    """Calculate the next workspace sequence number (e.g. Workspace 01 -> 2)."""
    projects = list_vault_projects()
    max_idx = 0
    pattern = re.compile(r"Workspace\s*(\d+)", re.IGNORECASE)
    for p in projects:
        ws_name = p.get("workspace_name", "")
        match = pattern.search(ws_name)
        if match:
            try:
                idx = int(match.group(1))
                if idx > max_idx:
                    max_idx = idx
            except ValueError:
                pass
    return max(max_idx + 1, 1)


def workspace_name_taken(name: str, exclude_project_id: Optional[str] = None) -> bool:
    """True when another project already uses this workspace name (case-insensitive)."""
    wanted = (name or "").strip().lower()
    if not wanted:
        return False
    for proj in list_vault_projects():
        if exclude_project_id and proj.get("project_id") == exclude_project_id:
            continue
        if (proj.get("workspace_name") or "").strip().lower() == wanted:
            return True
    return False


def save_media_metadata(target_dir: str, item_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save or update media item metadata in target directory's meta.json.
    Sets item_data["saved_at"] = time.time() if not already set.
    """
    if not os.path.isabs(target_dir):
        if (
            target_dir in storage_manager.CATEGORY_MAP
            or target_dir in storage_manager.CATEGORY_MAP.values()
        ):
            target_dir = storage_manager.get_category_folder(target_dir)
        else:
            target_dir = os.path.join(storage_manager.get_storage_root(), target_dir)

    os.makedirs(target_dir, exist_ok=True)

    if not item_data.get("saved_at"):
        item_data["saved_at"] = time.time()

    meta_path = os.path.join(target_dir, INDEX_FILE_NAME)
    current_items: List[Dict[str, Any]] = []

    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    current_items = [it for it in loaded if isinstance(it, dict)]
                elif isinstance(loaded, dict):
                    current_items = [loaded]
        except Exception:
            current_items = []

    # Update if item with same ID exists, otherwise append
    item_id = item_data.get("id")
    updated = False
    for idx, existing in enumerate(current_items):
        if item_id and existing.get("id") == item_id:
            current_items[idx] = item_data
            updated = True
            break

    if not updated:
        current_items.append(item_data)

    _atomic_write_json(meta_path, current_items)

    return item_data


def list_vault_items() -> List[Dict[str, Any]]:
    """
    Scan get_storage_root() for all meta.json files.
    Return a flat list of media items sorted by saved_at descending.
    """
    root = storage_manager.get_storage_root()
    items: List[Dict[str, Any]] = []

    if not os.path.exists(root):
        return items

    for current_dir, _, files in os.walk(root):
        if INDEX_FILE_NAME in files:
            meta_path = os.path.join(current_dir, INDEX_FILE_NAME)
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for entry in data:
                            if isinstance(entry, dict):
                                if "files" in entry and isinstance(entry["files"], list):
                                    items.extend(entry["files"])
                                else:
                                    items.append(entry)
                    elif isinstance(data, dict):
                        if "files" in data and isinstance(data["files"], list):
                            items.extend(data["files"])
                        else:
                            items.append(data)
            except Exception:
                continue

    items.sort(key=_extract_saved_at, reverse=True)
    return items


def delete_vault_item(item_id: str) -> str:
    """Delete one media item by id.

    Returns "deleted", "locked" (file still open elsewhere) or "not_found".
    The metadata entry is only removed once the file is really gone, so a failed
    delete no longer leaves an untracked orphan on disk.
    """
    root = storage_manager.get_storage_root()
    if not os.path.exists(root):
        return "not_found"

    for current_dir, _, files in os.walk(root):
        if INDEX_FILE_NAME not in files:
            continue
        meta_path = os.path.join(current_dir, INDEX_FILE_NAME)
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        item_found = False
        item_to_delete: Optional[Dict[str, Any]] = None
        remaining_items: List[Dict[str, Any]] = []

        if isinstance(data, dict):
            data = [data]

        if isinstance(data, list):
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                if entry.get("id") == item_id:
                    item_found = True
                    item_to_delete = entry
                elif "files" in entry and isinstance(entry["files"], list):
                    new_files = []
                    for f in entry["files"]:
                        if isinstance(f, dict) and f.get("id") == item_id:
                            item_found = True
                            item_to_delete = f
                        else:
                            new_files.append(f)
                    entry["files"] = new_files
                    remaining_items.append(entry)
                else:
                    remaining_items.append(entry)

        if not item_found:
            continue

        file_path = item_to_delete.get("file_path") if item_to_delete else None
        if file_path and _is_inside_storage(file_path, root) and os.path.isfile(file_path):
            if not _safe_remove_path(file_path):
                return "locked"

        thumb_path = item_to_delete.get("thumbnail_path") if item_to_delete else None
        if thumb_path and _is_inside_storage(thumb_path, root) and os.path.isfile(thumb_path):
            _safe_remove_path(thumb_path)
            thumb_parent = os.path.dirname(thumb_path)
            try:
                if os.path.basename(thumb_parent) == "covers" and not os.listdir(thumb_parent):
                    os.rmdir(thumb_parent)
            except OSError:
                pass

        has_files_left = False
        for r in remaining_items:
            if isinstance(r, dict) and "files" in r:
                if len(r["files"]) > 0:
                    has_files_left = True
                    break
            else:
                has_files_left = True
                break

        if remaining_items and has_files_left:
            try:
                _atomic_write_json(meta_path, remaining_items)
            except Exception:
                return "locked"
        else:
            try:
                if os.path.exists(meta_path):
                    os.remove(meta_path)
            except Exception:
                return "locked"

            if os.path.abspath(current_dir) != os.path.abspath(root):
                try:
                    if os.path.exists(current_dir) and not os.listdir(current_dir):
                        os.rmdir(current_dir)
                except OSError:
                    pass

        return "deleted"

    return "not_found"


def _find_item_in_entries(entries: List[Dict[str, Any]], item_id: str):
    """Return (target_item, sibling_items) matching item_id inside parsed meta.json entries."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        files_list = entry.get("files")
        if isinstance(files_list, list):
            for candidate in files_list:
                if isinstance(candidate, dict) and candidate.get("id") == item_id:
                    return candidate, files_list
        elif entry.get("id") == item_id:
            return entry, entries
    return None, None


def _rename_physical_file(abs_old: str, new_path: str):
    """Rename a physical media file inside the vault with brief Windows lock retries.

    Returns ``(did_rename, error_status)`` where ``error_status`` is ``None``,
    ``"conflict"``, or ``"locked"``.
    """
    if not abs_old or not os.path.exists(abs_old) or abs_old == new_path:
        return False, None

    if os.path.exists(new_path):
        try:
            same_target = os.path.samefile(abs_old, new_path)
        except OSError:
            same_target = False
        if not same_target:
            return False, "conflict"

    for attempt in range(3):
        try:
            os.rename(abs_old, new_path)
            return True, None
        except PermissionError:
            if attempt == 2:
                return False, "locked"
            gc.collect()
            time.sleep(0.1)
        except FileExistsError:
            return False, "conflict"
        except OSError:
            return False, "locked"
    return False, "locked"


def rename_vault_item(item_id: str, new_name: str, title_only: bool = False) -> Dict[str, Any]:
    """Rename a media item's display title or physical file stem (with locked extension).

    When ``title_only`` is True (used for AI Clipper / Video Trimmer cards), only the
    card's ``title`` field in ``meta.json`` is updated and the file on disk is left intact.
    Returns ``{"status": "renamed", "item": ...}`` or ``{"status": code}`` where
    ``code`` is one of ``"not_found"``, ``"invalid"``, ``"conflict"``, or ``"locked"``.
    """
    root = storage_manager.get_storage_root()
    if not os.path.exists(root):
        return {"status": "not_found"}

    root_abs = os.path.abspath(root)

    for current_dir, _, files in os.walk(root):
        if INDEX_FILE_NAME not in files:
            continue
        meta_path = os.path.join(current_dir, INDEX_FILE_NAME)
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        was_dict = isinstance(data, dict)
        entries = [data] if was_dict else ([e for e in data if isinstance(e, dict)] if isinstance(data, list) else None)
        if entries is None:
            continue

        target_item, siblings = _find_item_in_entries(entries, item_id)
        if not target_item:
            continue

        payload_to_write: Any = entries[0] if was_dict and len(entries) == 1 else entries

        if title_only:
            clean_title = " ".join(str(new_name or "").split()).strip()
            if not clean_title:
                return {"status": "invalid"}
            target_item["title"] = clean_title
            try:
                _atomic_write_json(meta_path, payload_to_write)
            except Exception:
                return {"status": "locked"}
            return {"status": "renamed", "item": target_item}

        old_path = target_item.get("file_path") or ""
        orig_filename = target_item.get("filename") or (os.path.basename(old_path) if old_path else "")
        if not orig_filename:
            return {"status": "invalid"}

        _, orig_ext = os.path.splitext(orig_filename)
        stem = " ".join(str(new_name or "").split()).strip()
        if orig_ext:
            if stem.lower() == orig_ext.lower():
                return {"status": "invalid"}
            if stem.lower().endswith(orig_ext.lower()):
                stem = stem[: -len(orig_ext)].strip()

        clean_stem = storage_manager.sanitize_name(stem)
        if not clean_stem:
            return {"status": "invalid"}

        new_filename = f"{clean_stem}{orig_ext}"
        parent_dir = os.path.dirname(os.path.abspath(old_path)) if old_path else os.path.abspath(current_dir)
        new_path = os.path.abspath(os.path.join(parent_dir, new_filename))

        if (old_path and not _is_inside_storage(old_path, root_abs)) or not _is_inside_storage(new_path, root_abs):
            return {"status": "invalid"}

        for sib in (siblings or []):
            if not isinstance(sib, dict) or sib is target_item:
                continue
            sib_path = sib.get("file_path") or ""
            sib_dir = os.path.dirname(os.path.abspath(sib_path)) if sib_path else os.path.abspath(current_dir)
            if os.path.normcase(sib_dir) == os.path.normcase(parent_dir) and (sib.get("filename") or "").lower() == new_filename.lower():
                return {"status": "conflict"}

        abs_old = os.path.abspath(old_path) if old_path else ""
        did_disk_rename, disk_err = _rename_physical_file(abs_old, new_path)
        if disk_err:
            return {"status": disk_err}

        rel = os.path.relpath(new_path, root_abs).replace("\\", "/")
        target_item["filename"] = new_filename
        target_item["title"] = new_filename
        target_item["file_path"] = new_path
        target_item["url"] = f"/media-vault/{rel}"

        try:
            _atomic_write_json(meta_path, payload_to_write)
        except Exception:
            if did_disk_rename and os.path.exists(new_path) and not os.path.exists(abs_old):
                try:
                    os.rename(new_path, abs_old)
                except OSError:
                    pass
            return {"status": "locked"}

        return {"status": "renamed", "item": target_item}

    return {"status": "not_found"}


def get_storage_stats() -> Dict[str, Any]:
    """
    Scan get_storage_root() and return total storage statistics.
    Excludes meta.json and hidden files.
    """
    root = storage_manager.get_storage_root()
    total_bytes = 0
    total_files = 0

    if os.path.exists(root):
        for dirpath, _, filenames in os.walk(root):
            if os.path.basename(dirpath) == "covers":
                continue
            for f in filenames:
                if f == INDEX_FILE_NAME or f.startswith("."):
                    continue
                # Partial downloads and temp files are not library content.
                if f.endswith((".part", ".ytdl", ".tmp")):
                    continue
                fp = os.path.join(dirpath, f)
                try:
                    total_bytes += os.path.getsize(fp)
                    total_files += 1
                except Exception:
                    pass

    return {
        "storage_root": os.path.abspath(root),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "total_gb": round(total_bytes / (1024 * 1024 * 1024), 2),
    }
