import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestJsRuntime(unittest.TestCase):
    def test_deno_is_found_without_an_activated_venv(self):
        """yt-dlp finds no YouTube formats without a JS runtime on PATH."""
        bin_dir = os.path.dirname(sys.executable)
        bare_path = os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep) if p != bin_dir)
        # A fresh process, so importing luna.app again does not disturb the other tests.
        out = subprocess.run(
            [sys.executable, "-c", "import shutil, luna.app; print(shutil.which('deno') or '')"],
            cwd=ROOT, env={**os.environ, "PATH": bare_path}, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.strip(), "deno is not on PATH after importing luna.app")


if __name__ == "__main__":
    unittest.main()
