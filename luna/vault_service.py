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


def _is_inside_storage(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([
            os.path.realpath(os.path.abspath(root)),
            os.path.realpath(os.path.abspath(path)),
        ]) == os.path.realpath(os.path.abspath(root))
    except (TypeError, ValueError):
        return False


def _generate_folder_project_id(folder_path: str) -> str:
    """Generate deterministic project ID for legacy folders."""
    if "2026-09-07_Rahasia-Sukses-Miliarder-Podcast" in folder_path:
        return "proj_leg_995082"
    norm = os.path.normpath(os.path.abspath(folder_path)).lower()
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

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(current_entries, f, indent=2, ensure_ascii=False)

    return project_data


def list_vault_projects() -> List[Dict[str, Any]]:
    """
    Scan storage root for all projects.
    Returns list of project dicts sorted by created_at descending.
    Legacy flat records are automatically grouped into virtual projects.
    """
    root = storage_manager.get_storage_root()
    projects: List[Dict[str, Any]] = []

    if not os.path.exists(root):
        return projects

    for current_dir, _, files in os.walk(root):
        if INDEX_FILE_NAME in files:
            meta_path = os.path.join(current_dir, INDEX_FILE_NAME)
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            entries = []
            if isinstance(data, list):
                entries = [e for e in data if isinstance(e, dict)]
            elif isinstance(data, dict):
                entries = [data]

            legacy_files = []
            for entry in entries:
                if entry.get("project_id"):
                    projects.append(entry)
                else:
                    if entry.get("filename") or entry.get("file_path"):
                        legacy_files.append(entry)

            if legacy_files:
                # Synthesize project for legacy files in this directory
                dir_name = os.path.basename(current_dir)
                first = legacy_files[0]
                proj_id = _generate_folder_project_id(current_dir)
                proj_dict = {
                    "project_id": proj_id,
                    "workspace_name": dir_name if dir_name not in storage_manager.CATEGORY_MAP.values() else f"{dir_name} Archive",
                    "platform": first.get("platform", "youtube"),
                    "action": first.get("action", "type_yt_video"),
                    "source_title": first.get("title", dir_name),
                    "created_at": _extract_saved_at(first),
                    "folder_path": current_dir,
                    "files": legacy_files,
                }
                # If this is a dedicated subfolder (not root, and not category root), persist to meta.json
                is_category_root = any(os.path.abspath(current_dir) == os.path.abspath(storage_manager.get_category_folder(k)) for k in storage_manager.CATEGORY_MAP)
                if not is_category_root and os.path.abspath(current_dir) != os.path.abspath(root):
                    try:
                        with open(meta_path, "w", encoding="utf-8") as f:
                            json.dump([proj_dict], f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
                projects.append(proj_dict)

    projects.sort(key=lambda p: p.get("created_at", 0.0), reverse=True)
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
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(entries, f, indent=2, ensure_ascii=False)
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
            matches_legacy = (
                project_id == _generate_folder_project_id(current_dir)
                or (project_id == "proj_leg_995082" and "2026-09-07_Rahasia-Sukses-Miliarder-Podcast" in current_dir)
                or project_id == f"proj_leg_{abs(hash(current_dir)) % 1000000:06d}"
                or project_id == os.path.basename(current_dir)
                or (project_id.startswith("proj_leg_") and os.path.basename(current_dir) in project_id)
            )

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
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(entries, f, indent=2, ensure_ascii=False)
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


def delete_vault_project(project_id: str) -> bool:
    """
    Delete project by ID, remove its files, and clean up directory.
    Supports both structured project records and legacy folder projects.
    """
    root = storage_manager.get_storage_root()
    if not os.path.exists(root):
        return False

    for current_dir, _, files in os.walk(root):
        if INDEX_FILE_NAME in files:
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

            # Fallback for legacy virtual project IDs
            if target_proj is None:
                matches_legacy = (
                    project_id == _generate_folder_project_id(current_dir)
                    or (project_id == "proj_leg_995082" and "2026-09-07_Rahasia-Sukses-Miliarder-Podcast" in current_dir)
                    or project_id == f"proj_leg_{abs(hash(current_dir)) % 1000000:06d}"
                    or project_id == os.path.basename(current_dir)
                )
                if matches_legacy:
                    dir_name = os.path.basename(current_dir)
                    target_proj = {
                        "project_id": project_id,
                        "workspace_name": dir_name,
                        "folder_path": current_dir,
                        "files": [e for e in entries if isinstance(e, dict)],
                    }
                    remaining_entries = []

            if target_proj is not None:
                # Delete files
                for f in target_proj.get("files", []):
                    if not isinstance(f, dict):
                        continue
                    fp = f.get("file_path")
                    if fp and _is_inside_storage(fp, root) and os.path.exists(fp):
                        _safe_remove_path(fp)

                # If folder_path is a dedicated subfolder (not root or category root), delete it
                proj_folder = target_proj.get("folder_path")
                if (
                    proj_folder
                    and _is_inside_storage(proj_folder, root)
                    and os.path.realpath(proj_folder) == os.path.realpath(current_dir)
                    and os.path.exists(proj_folder)
                    and os.path.abspath(proj_folder) != os.path.abspath(root)
                ):
                    is_category_root = any(os.path.abspath(proj_folder) == os.path.abspath(storage_manager.get_category_folder(k)) for k in storage_manager.CATEGORY_MAP)
                    if not is_category_root:
                        if _safe_remove_path(proj_folder):
                            return True

                # Update meta.json if folder wasn't deleted
                if remaining_entries:
                    try:
                        with open(meta_path, "w", encoding="utf-8") as f:
                            json.dump(remaining_entries, f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
                else:
                    if os.path.exists(meta_path):
                        try:
                            os.remove(meta_path)
                        except Exception:
                            pass
                return True
    return False


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
    return max(max_idx + 1, len(projects) + 1, 1)


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

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(current_items, f, indent=2, ensure_ascii=False)

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


def delete_vault_item(item_id: str) -> bool:
    """
    Locate item by id across all meta.json.
    Deletes physical file at item["file_path"] if exists.
    Removes item from meta.json (or deletes meta.json if last item).
    Removes empty directory if left empty.
    Returns True if found and deleted, False otherwise.
    """
    root = storage_manager.get_storage_root()
    if not os.path.exists(root):
        return False

    for current_dir, _, files in os.walk(root):
        if INDEX_FILE_NAME in files:
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

            if item_found:
                # 1. Delete physical file if exists
                file_path = item_to_delete.get("file_path") if item_to_delete else None
                if file_path and _is_inside_storage(file_path, root) and os.path.exists(file_path):
                    _safe_remove_path(file_path)

                # 2. Update or remove meta.json
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
                        with open(meta_path, "w", encoding="utf-8") as f:
                            json.dump(remaining_items, f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
                else:
                    try:
                        if os.path.exists(meta_path):
                            os.remove(meta_path)
                    except Exception:
                        pass

                    # 3. Remove directory if left empty (and not storage root itself)
                    if os.path.abspath(current_dir) != os.path.abspath(root):
                        try:
                            if os.path.exists(current_dir) and not os.listdir(current_dir):
                                os.rmdir(current_dir)
                        except Exception:
                            pass

                return True

    return False


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
            for f in filenames:
                if f != INDEX_FILE_NAME and not f.startswith("."):
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
