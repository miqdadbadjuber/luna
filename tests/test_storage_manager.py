import datetime
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import storage_manager


class TestStorageManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for isolated file operations during testing
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_constants(self):
        """Verify required constants and category mapping."""
        self.assertEqual(storage_manager.DEFAULT_D_PATH, r"D:\Luna-Media")
        self.assertEqual(
            storage_manager.FALLBACK_PATH,
            os.path.join(storage_manager.BASE_DIR, "output"),
        )
        expected_category_map = {
            "youtube_ai_clip": "01-AI-Clips",
            "youtube_video": "02-YouTube-Full",
            "instagram_video": "03-Instagram-Reels",
            "tiktok_video": "04-TikTok-Clean",
            "youtube_audio": "05-Audio-MP3",
        }
        self.assertEqual(storage_manager.CATEGORY_MAP, expected_category_map)

    def test_sanitize_name(self):
        """Test removal of invalid chars (\\/*?:\"<>|#) and whitespace normalization."""
        dirty = 'Video\\Title/With:Bad*Chars?"And<Arrows>|Pipe#Hash'
        cleaned = storage_manager.sanitize_name(dirty)
        self.assertEqual(cleaned, "VideoTitleWithBadCharsAndArrowsPipeHash")

        # Test spacing and trimming
        spaced = "   My   Video  :  Title   #1   "
        self.assertEqual(storage_manager.sanitize_name(spaced), "My Video Title 1")

        # Test empty or falsy inputs
        self.assertEqual(storage_manager.sanitize_name(""), "")
        self.assertEqual(storage_manager.sanitize_name(None), "")
        self.assertEqual(storage_manager.sanitize_name(":::###???"), "")

        # Test preserved valid characters (alphanumeric, dash, parentheses, underscore)
        normal = "Podcast-Episode_(1080p)_v2"
        self.assertEqual(storage_manager.sanitize_name(normal), normal)

    def test_format_media_filename(self):
        """Test formatting of media filenames."""
        # Without prefix
        fn1 = storage_manager.format_media_filename(
            "Sample Video", "mp4", date="2026-09-07"
        )
        self.assertEqual(fn1, "2026-09-07_Sample Video.mp4")

        # With prefix
        fn2 = storage_manager.format_media_filename(
            "Podcast Interview", "mp4", prefix="1080p", date="2026-09-07"
        )
        self.assertEqual(fn2, "2026-09-07_1080p_Podcast Interview.mp4")

        # Prefix with trailing underscore and ext with leading dot
        fn3 = storage_manager.format_media_filename(
            "Song Audio", ".mp3", prefix="320kbps_", date="2026-09-07"
        )
        self.assertEqual(fn3, "2026-09-07_320kbps_Song Audio.mp3")

        # Dirty title with invalid characters
        fn4 = storage_manager.format_media_filename(
            "Great / Video: #1?", "mp4", prefix="clean", date="2026-09-07"
        )
        self.assertEqual(fn4, "2026-09-07_clean_Great Video 1.mp4")

        # Default date should match today
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        fn_today = storage_manager.format_media_filename("Daily Vlog", "mp4")
        self.assertTrue(fn_today.startswith(f"{today_str}_"))
        self.assertTrue(fn_today.endswith("Daily Vlog.mp4"))

        # Empty title fallback
        fn_empty = storage_manager.format_media_filename("", "mp4", date="2026-09-07")
        self.assertEqual(fn_empty, "2026-09-07_media.mp4")

    def test_format_clip_folder(self):
        """Test formatting of clip folder names."""
        folder = storage_manager.format_clip_folder(
            "How to Make AI Shorts", date="2026-09-07"
        )
        self.assertEqual(folder, "2026-09-07_How to Make AI Shorts")

        # Dirty title
        dirty_folder = storage_manager.format_clip_folder(
            "Tutorial: AI Shorts #Viral?", date="2026-09-07"
        )
        self.assertEqual(dirty_folder, "2026-09-07_Tutorial AI Shorts Viral")

        # Default date should match today
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        folder_today = storage_manager.format_clip_folder("Live Stream")
        self.assertEqual(folder_today, f"{today_str}_Live Stream")

        # Empty title fallback
        folder_empty = storage_manager.format_clip_folder("", date="2026-09-07")
        self.assertEqual(folder_empty, "2026-09-07_media")

    def test_get_storage_root_fallback_when_d_not_present(self):
        """Verify fallback to FALLBACK_PATH when D drive does not exist."""
        # By default on machines without D:\ or with default non-existent path
        with patch.dict(os.environ, {}, clear=False):
            if "MEDIA_STORAGE_DIR" in os.environ:
                del os.environ["MEDIA_STORAGE_DIR"]

            # If D:\Luna-Media is not writable, must return FALLBACK_PATH
            if not storage_manager.is_writable(storage_manager.DEFAULT_D_PATH):
                root = storage_manager.get_storage_root()
                self.assertEqual(root, os.path.abspath(storage_manager.FALLBACK_PATH))
                self.assertTrue(os.path.isdir(root))

    def test_get_storage_root_custom_env_writable(self):
        """Verify that a writable path (via env MEDIA_STORAGE_DIR) is used."""
        custom_vault = os.path.join(self.test_dir, "Custom-Vault")
        with patch.dict(os.environ, {"MEDIA_STORAGE_DIR": custom_vault}):
            root = storage_manager.get_storage_root()
            self.assertEqual(root, os.path.abspath(custom_vault))
            self.assertTrue(os.path.isdir(root))

    def test_get_storage_root_writable_default_d_path(self):
        """Verify that when DEFAULT_D_PATH is writable, it returns it."""
        mock_d = os.path.join(self.test_dir, "Mock-D-Drive")
        with patch.object(storage_manager, "DEFAULT_D_PATH", mock_d):
            with patch.dict(os.environ, {}, clear=False):
                if "MEDIA_STORAGE_DIR" in os.environ:
                    del os.environ["MEDIA_STORAGE_DIR"]
                root = storage_manager.get_storage_root()
                self.assertEqual(root, os.path.abspath(mock_d))
                self.assertTrue(os.path.isdir(root))

    def test_get_category_folder_creates_and_returns_path(self):
        """Verify get_category_folder for all actions creates and returns directory."""
        custom_vault = os.path.join(self.test_dir, "Vault-Categories")
        with patch.dict(os.environ, {"MEDIA_STORAGE_DIR": custom_vault}):
            for action, folder_name in storage_manager.CATEGORY_MAP.items():
                cat_dir = storage_manager.get_category_folder(action)
                expected_dir = os.path.join(os.path.abspath(custom_vault), folder_name)
                self.assertEqual(cat_dir, expected_dir)
                self.assertTrue(os.path.isdir(cat_dir))

    def test_get_category_folder_unmapped_action(self):
        """Verify get_category_folder handles unmapped action cleanly."""
        custom_vault = os.path.join(self.test_dir, "Vault-Unmapped")
        with patch.dict(os.environ, {"MEDIA_STORAGE_DIR": custom_vault}):
            cat_dir = storage_manager.get_category_folder("custom_action")
            expected_dir = os.path.join(os.path.abspath(custom_vault), "custom_action")
            self.assertEqual(cat_dir, expected_dir)
            self.assertTrue(os.path.isdir(cat_dir))


if __name__ == "__main__":
    unittest.main()
