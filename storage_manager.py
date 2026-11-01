import datetime
import os
import re
from typing import Optional, Union

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_D_PATH = r"D:\Luna-Media" if os.name == "nt" else os.path.join(BASE_DIR, "output")
FALLBACK_PATH = os.path.join(BASE_DIR, "output")

CATEGORY_MAP = {
    "youtube_ai_clip": "01-AI-Clips",
    "youtube_video": "02-YouTube-Full",
    "instagram_video": "03-Instagram-Reels",
    "tiktok_video": "04-TikTok-Clean",
    "youtube_audio": "05-Audio-MP3",
}

ACTION_CATEGORY_MAP = {
    "type_yt_ai_clip": "01-AI-Clips",
    "ai_clip": "01-AI-Clips",
    "youtube_ai_clip": "01-AI-Clips",
    "type_yt_video": "02-YouTube-Full",
    "type_yt_short": "02-YouTube-Full",
    "type_yt_clip": "02-YouTube-Full",
    "clip": "02-YouTube-Full",
    "manual_clip": "02-YouTube-Full",
    "youtube_video": "02-YouTube-Full",
    "type_ig_reels": "03-Instagram-Reels",
    "ig_reels": "03-Instagram-Reels",
    "instagram_video": "03-Instagram-Reels",
    "type_tt_video": "04-TikTok-Clean",
    "tt_video": "04-TikTok-Clean",
    "tiktok_video": "04-TikTok-Clean",
    "type_yt_mp3": "05-Audio-MP3",
    "type_tt_mp3": "05-Audio-MP3",
    "mp3": "05-Audio-MP3",
    "audio_mp3": "05-Audio-MP3",
    "youtube_audio": "05-Audio-MP3",
}


def is_writable(path: str) -> bool:
    """Check if a directory path can be created and written to."""
    try:
        os.makedirs(path, exist_ok=True)
        test_file = os.path.join(path, f".write_test_{os.getpid()}")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("test")
        if os.path.exists(test_file):
            os.remove(test_file)
        return True
    except Exception:
        return False


def get_storage_root() -> str:
    """Return writable path: tries D:\\Luna-Media (or MEDIA_STORAGE_DIR), falls back to output/."""
    target_path = os.getenv("MEDIA_STORAGE_DIR") or DEFAULT_D_PATH
    if is_writable(target_path):
        return os.path.abspath(target_path)

    os.makedirs(FALLBACK_PATH, exist_ok=True)
    return os.path.abspath(FALLBACK_PATH)


def get_category_folder(action: str) -> str:
    """Create and return category directory based on action."""
    root = get_storage_root()
    folder_name = CATEGORY_MAP.get(action) or ACTION_CATEGORY_MAP.get(action)
    if not folder_name:
        if action in CATEGORY_MAP.values():
            folder_name = action
        else:
            folder_name = sanitize_name(action) or "00-Misc"

    folder_path = os.path.join(root, folder_name)
    os.makedirs(folder_path, exist_ok=True)
    return folder_path


def get_workspace_folder(action: str, workspace_name: str) -> str:
    """Create and return category directory with subfolder for the workspace."""
    cat_folder = get_category_folder(action)
    ws_clean = sanitize_name(workspace_name) or "Workspace 01"
    ws_dir = os.path.join(cat_folder, ws_clean)
    os.makedirs(ws_dir, exist_ok=True)
    return ws_dir


def sanitize_name(name: str, max_length: int = 80) -> str:
    """Remove invalid chars (\\/*?:\"<>|#), normalize whitespace, and cap length to avoid MAX_PATH issues."""
    if not name:
        return ""
    cleaned = re.sub(r'[\\/*?:"<>|#]', "", str(name))
    cleaned = " ".join(cleaned.split()).strip()
    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    return cleaned


def format_media_filename(
    title: str,
    ext: str,
    prefix: str = "",
    date: Optional[Union[datetime.date, str]] = None,
) -> str:
    """Return YYYY-MM-DD_[prefix_]clean_title.ext."""
    if date is None:
        date_str = datetime.date.today().strftime("%Y-%m-%d")
    elif isinstance(date, (datetime.date, datetime.datetime)):
        date_str = date.strftime("%Y-%m-%d")
    else:
        date_str = str(date).strip()

    clean_title = sanitize_name(title) or "media"
    clean_ext = ext.lstrip(".")

    prefix_clean = prefix.strip("_").strip() if prefix else ""
    prefix_part = f"{prefix_clean}_" if prefix_clean else ""

    return f"{date_str}_{prefix_part}{clean_title}.{clean_ext}"


def format_clip_folder(
    title: str,
    date: Optional[Union[datetime.date, str]] = None,
) -> str:
    """Return YYYY-MM-DD_clean_title."""
    if date is None:
        date_str = datetime.date.today().strftime("%Y-%m-%d")
    elif isinstance(date, (datetime.date, datetime.datetime)):
        date_str = date.strftime("%Y-%m-%d")
    else:
        date_str = str(date).strip()

    clean_title = sanitize_name(title) or "media"
    return f"{date_str}_{clean_title}"


def migrate_storage(old_root: str, new_root: str) -> dict:
    """Migrate media directories and metadata from old_root (and fallback output/) to new_root."""
    import shutil

    old_root = os.path.abspath(old_root)
    new_root = os.path.abspath(new_root)

    if not is_writable(new_root):
        raise ValueError(f"Destination directory '{new_root}' is not writable.")

    sources_to_migrate = []
    if old_root != new_root and os.path.exists(old_root):
        sources_to_migrate.append(old_root)
    fallback = os.path.abspath(FALLBACK_PATH)
    if os.path.exists(fallback) and fallback != new_root and fallback not in sources_to_migrate:
        sources_to_migrate.append(fallback)

    if not sources_to_migrate:
        return {"migrated_files": 0, "status": "same_directory"}

    migrated_count = 0
    for src_dir in sources_to_migrate:
        if not os.path.exists(src_dir) or src_dir == new_root:
            continue
        for item in os.listdir(src_dir):
            src_item = os.path.join(src_dir, item)
            dst_item = os.path.join(new_root, item)
            if os.path.isdir(src_item):
                if not os.path.exists(dst_item):
                    try:
                        shutil.move(src_item, dst_item)
                        migrated_count += 1
                    except Exception:
                        pass
                else:
                    for root_dir, dirs, files in os.walk(src_item):
                        rel = os.path.relpath(root_dir, src_item)
                        target_sub = os.path.join(dst_item, rel)
                        os.makedirs(target_sub, exist_ok=True)
                        for f in files:
                            s_f = os.path.join(root_dir, f)
                            d_f = os.path.join(target_sub, f)
                            try:
                                if not os.path.exists(d_f):
                                    shutil.move(s_f, d_f)
                                    migrated_count += 1
                                else:
                                    shutil.copy2(s_f, d_f)
                                    try:
                                        os.remove(s_f)
                                    except Exception:
                                        pass
                                    migrated_count += 1
                            except Exception:
                                pass
                    try:
                        shutil.rmtree(src_item, ignore_errors=True)
                    except Exception:
                        pass
            elif os.path.isfile(src_item) and item.endswith((".json", ".mp4", ".mp3", ".webm", ".mkv", ".jpg", ".png")):
                try:
                    if not os.path.exists(dst_item):
                        shutil.move(src_item, dst_item)
                        migrated_count += 1
                    else:
                        shutil.copy2(src_item, dst_item)
                        try:
                            os.remove(src_item)
                        except Exception:
                            pass
                        migrated_count += 1
                except Exception:
                    pass

    return {"migrated_files": migrated_count, "status": "success"}
