import unittest

from luna.clipper.highlights import clean_caption


class TestCaptionSanitizer(unittest.TestCase):
    def test_clean_caption_removes_emojis(self):
        raw = "This is a great caption! 🚀🔥 Be sure to try it 💡"
        cleaned = clean_caption(raw)
        self.assertNotIn("🚀", cleaned)
        self.assertNotIn("🔥", cleaned)
        self.assertNotIn("💡", cleaned)
        self.assertEqual(cleaned, "This is a great caption! Be sure to try it")

    def test_clean_caption_removes_hashtags(self):
        raw = "Focus on the process, not the outcome #Motivation #Success #Shorts"
        cleaned = clean_caption(raw)
        self.assertNotIn("#Motivasi", cleaned)
        self.assertNotIn("#Success", cleaned)
        self.assertNotIn("#Shorts", cleaned)
        self.assertNotIn("#", cleaned)
        self.assertEqual(cleaned, "Focus on the process, not the outcome")

    def test_clean_caption_replaces_em_dashes(self):
        raw = "The key to success—not just hard work—is consistency."
        cleaned = clean_caption(raw)
        self.assertNotIn("—", cleaned)
        self.assertNotIn("–", cleaned)
        self.assertIn("The key to success, not just hard work, is consistency.", cleaned)

    def test_clean_caption_handles_empty_or_none(self):
        self.assertEqual(clean_caption(""), "")
        self.assertEqual(clean_caption(None), "")


if __name__ == "__main__":
    unittest.main()
