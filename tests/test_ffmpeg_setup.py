import sys
import types
import unittest
from unittest.mock import patch

from luna import ffmpeg_setup


class TestEnsureFfmpeg(unittest.TestCase):
    def test_existing_install_is_left_alone(self):
        fake = types.SimpleNamespace(add_paths=unittest.mock.Mock())
        with patch("shutil.which", return_value="/bin/x"), patch.dict(sys.modules, {"static_ffmpeg": fake}):
            self.assertTrue(ffmpeg_setup.ensure_ffmpeg())
        fake.add_paths.assert_not_called()

    def test_missing_ffprobe_triggers_the_download(self):
        found = []
        fake = types.SimpleNamespace(add_paths=lambda: found.append(True))
        with patch("shutil.which", side_effect=lambda name: "/bin/x" if name == "ffmpeg" or found else None), \
                patch.dict(sys.modules, {"static_ffmpeg": fake}):
            self.assertTrue(ffmpeg_setup.ensure_ffmpeg())
        self.assertEqual(found, [True])

    def test_failed_download_reports_false_without_crashing(self):
        fake = types.SimpleNamespace(add_paths=unittest.mock.Mock(side_effect=OSError("offline")))
        with patch("shutil.which", return_value=None), patch.dict(sys.modules, {"static_ffmpeg": fake}):
            self.assertFalse(ffmpeg_setup.ensure_ffmpeg())


if __name__ == "__main__":
    unittest.main()
