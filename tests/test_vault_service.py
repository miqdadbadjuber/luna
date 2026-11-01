import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

import storage_manager
import vault_service


class TestVaultService(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.env_patch = patch.dict(os.environ, {"MEDIA_STORAGE_DIR": self.test_dir})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_constants(self):
        """Verify INDEX_FILE_NAME is meta.json."""
        self.assertEqual(vault_service.INDEX_FILE_NAME, "meta.json")

    def test_save_media_metadata_sets_saved_at_and_creates_meta(self):
        """Verify save_media_metadata sets saved_at, creates meta.json, and returns item."""
        target_dir = os.path.join(self.test_dir, "02-YouTube-Full")
        item = {
            "id": "item_1",
            "title": "Video 1",
            "filename": "2026-09-07_Video 1.mp4",
            "file_path": os.path.join(target_dir, "2026-09-07_Video 1.mp4"),
        }
        before_time = time.time()
        result = vault_service.save_media_metadata(target_dir, item)
        after_time = time.time()

        self.assertEqual(result["id"], "item_1")
        self.assertIn("saved_at", result)
        self.assertGreaterEqual(result["saved_at"], before_time)
        self.assertLessEqual(result["saved_at"], after_time)

        meta_file = os.path.join(target_dir, "meta.json")
        self.assertTrue(os.path.exists(meta_file))
        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], "item_1")

    def test_save_media_metadata_preserves_existing_saved_at(self):
        """Verify custom saved_at is preserved when already present."""
        target_dir = os.path.join(self.test_dir, "03-Instagram-Reels")
        custom_time = 1700000000.0
        item = {
            "id": "ig_1",
            "title": "Reel 1",
            "saved_at": custom_time,
        }
        result = vault_service.save_media_metadata(target_dir, item)
        self.assertEqual(result["saved_at"], custom_time)

    def test_save_media_metadata_updates_existing_item(self):
        """Verify saving an item with the same id updates it in place."""
        target_dir = os.path.join(self.test_dir, "04-TikTok-Clean")
        item1 = {"id": "tk_1", "title": "Old Title", "caption": "Old"}
        item2 = {"id": "tk_2", "title": "Other Video"}
        vault_service.save_media_metadata(target_dir, item1)
        vault_service.save_media_metadata(target_dir, item2)

        # Update item1
        item1_updated = {"id": "tk_1", "title": "New Title", "caption": "Updated"}
        vault_service.save_media_metadata(target_dir, item1_updated)

        meta_file = os.path.join(target_dir, "meta.json")
        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(len(data), 2)
        titles = {i["id"]: i["title"] for i in data}
        self.assertEqual(titles["tk_1"], "New Title")
        self.assertEqual(titles["tk_2"], "Other Video")

    def test_save_media_metadata_resolves_relative_and_category(self):
        """Verify save_media_metadata resolves category names to category folder."""
        item = {"id": "yt_cat_1", "title": "Category Test"}
        vault_service.save_media_metadata("02-YouTube-Full", item)

        expected_meta = os.path.join(self.test_dir, "02-YouTube-Full", "meta.json")
        self.assertTrue(os.path.exists(expected_meta))

    def test_list_vault_items_empty(self):
        """Verify list_vault_items returns empty list when no items exist."""
        items = vault_service.list_vault_items()
        self.assertEqual(items, [])

    def test_list_vault_items_sorted_saved_at_desc(self):
        """Verify list_vault_items returns flat list sorted by saved_at descending."""
        cat1 = os.path.join(self.test_dir, "01-AI-Clips", "clip_folder")
        cat2 = os.path.join(self.test_dir, "05-Audio-MP3")

        item_old = {"id": "item_old", "title": "Old", "saved_at": 100.0}
        item_mid = {"id": "item_mid", "title": "Mid", "saved_at": 200.0}
        item_new = {"id": "item_new", "title": "New", "saved_at": 300.0}

        vault_service.save_media_metadata(cat1, item_old)
        vault_service.save_media_metadata(cat2, item_new)
        vault_service.save_media_metadata(cat1, item_mid)

        items = vault_service.list_vault_items()
        self.assertEqual(len(items), 3)
        self.assertEqual([i["id"] for i in items], ["item_new", "item_mid", "item_old"])

    def test_list_vault_items_handles_dict_meta_and_corrupted_json(self):
        """Verify list_vault_items handles dict-based meta.json and ignores invalid JSON."""
        dict_dir = os.path.join(self.test_dir, "Single-Item")
        os.makedirs(dict_dir, exist_ok=True)
        with open(os.path.join(dict_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "single_dict", "saved_at": 500.0}, f)

        corrupt_dir = os.path.join(self.test_dir, "Corrupted")
        os.makedirs(corrupt_dir, exist_ok=True)
        with open(os.path.join(corrupt_dir, "meta.json"), "w", encoding="utf-8") as f:
            f.write("{invalid-json-format")

        items = vault_service.list_vault_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "single_dict")

    def test_get_storage_stats(self):
        """Verify get_storage_stats calculates total files, bytes, mb, and gb correctly."""
        media_dir = os.path.join(self.test_dir, "02-YouTube-Full")
        os.makedirs(media_dir, exist_ok=True)

        # Create 1 MB file (1,048,576 bytes)
        file1 = os.path.join(media_dir, "video1.mp4")
        with open(file1, "wb") as f:
            f.write(b"0" * (1024 * 1024))

        # Create 2 MB file (2,097,152 bytes)
        file2 = os.path.join(media_dir, "video2.mp4")
        with open(file2, "wb") as f:
            f.write(b"0" * (2 * 1024 * 1024))

        # Create meta.json (should be excluded from media count & bytes)
        meta_file = os.path.join(media_dir, "meta.json")
        with open(meta_file, "w", encoding="utf-8") as f:
            f.write(json.dumps([{"id": "1"}, {"id": "2"}]))

        # Create hidden test file (should be excluded)
        hidden_file = os.path.join(media_dir, ".hidden_test")
        with open(hidden_file, "w", encoding="utf-8") as f:
            f.write("hidden")

        stats = vault_service.get_storage_stats()
        self.assertEqual(stats["storage_root"], os.path.abspath(self.test_dir))
        self.assertEqual(stats["total_files"], 2)
        self.assertEqual(stats["total_bytes"], 3 * 1024 * 1024)
        self.assertEqual(stats["total_mb"], 3.0)
        self.assertEqual(stats["total_gb"], 0.0)

    def test_delete_vault_item_removes_file_meta_and_empty_dir(self):
        """Verify delete_vault_item removes file, meta.json, and empty directory."""
        clip_dir = os.path.join(self.test_dir, "01-AI-Clips", "2026-09-07_TestClip")
        os.makedirs(clip_dir, exist_ok=True)
        media_file = os.path.join(clip_dir, "clip_01.mp4")
        with open(media_file, "wb") as f:
            f.write(b"dummy clip content")

        item = {
            "id": "clip_to_delete",
            "title": "Clip To Delete",
            "file_path": media_file,
        }
        vault_service.save_media_metadata(clip_dir, item)

        self.assertTrue(os.path.exists(media_file))
        self.assertTrue(os.path.exists(os.path.join(clip_dir, "meta.json")))
        self.assertTrue(os.path.exists(clip_dir))

        deleted = vault_service.delete_vault_item("clip_to_delete")
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(media_file))
        self.assertFalse(os.path.exists(os.path.join(clip_dir, "meta.json")))
        # Empty clip_dir should be removed
        self.assertFalse(os.path.exists(clip_dir))

    def test_delete_vault_item_with_remaining_items_preserves_dir(self):
        """Verify delete_vault_item updates meta.json when other items remain."""
        cat_dir = os.path.join(self.test_dir, "02-YouTube-Full")
        os.makedirs(cat_dir, exist_ok=True)

        file1 = os.path.join(cat_dir, "vid1.mp4")
        with open(file1, "wb") as f:
            f.write(b"vid1")

        file2 = os.path.join(cat_dir, "vid2.mp4")
        with open(file2, "wb") as f:
            f.write(b"vid2")

        vault_service.save_media_metadata(cat_dir, {"id": "del_1", "file_path": file1})
        vault_service.save_media_metadata(cat_dir, {"id": "keep_2", "file_path": file2})

        deleted = vault_service.delete_vault_item("del_1")
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(file1))
        self.assertTrue(os.path.exists(file2))
        self.assertTrue(os.path.exists(os.path.join(cat_dir, "meta.json")))

        items = vault_service.list_vault_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "keep_2")

    def test_delete_vault_item_not_found(self):
        """Verify delete_vault_item returns False when item id does not exist."""
        result = vault_service.delete_vault_item("non_existent_id")
        self.assertFalse(result)

    def test_delete_vault_item_does_not_remove_file_outside_storage(self):
        outside_dir = tempfile.mkdtemp()
        try:
            outside_file = os.path.join(outside_dir, "keep.txt")
            with open(outside_file, "w", encoding="utf-8") as f:
                f.write("keep")

            item_dir = os.path.join(self.test_dir, "category")
            os.makedirs(item_dir)
            with open(os.path.join(item_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump([{"id": "unsafe", "file_path": outside_file}], f)

            self.assertTrue(vault_service.delete_vault_item("unsafe"))
            self.assertTrue(os.path.exists(outside_file))
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)

    def test_delete_vault_item_when_file_already_deleted(self):
        """Verify delete_vault_item succeeds even if physical file was already missing."""
        cat_dir = os.path.join(self.test_dir, "03-Instagram-Reels")
        missing_file = os.path.join(cat_dir, "already_gone.mp4")

        vault_service.save_media_metadata(cat_dir, {"id": "missing_file_item", "file_path": missing_file})

        deleted = vault_service.delete_vault_item("missing_file_item")
        self.assertTrue(deleted)
        self.assertEqual(vault_service.list_vault_items(), [])


if __name__ == "__main__":
    unittest.main()
