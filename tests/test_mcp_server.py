import asyncio
import os
import tempfile
import unittest

from tests import mcp_simulation


class TestMcpServer(unittest.TestCase):
    """Runs the simulated agent session: a real MCP client over stdio against a fake Luna."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = os.path.join(cls.tmp.name, "clips")
        cls.answers = asyncio.run(mcp_simulation.run(cls.folder, echo=lambda _: None))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_lists_every_tool(self):
        self.assertEqual(self.answers["tools"], sorted([
            "cancel_job", "check_setup", "clip_video", "get_clips",
            "job_status", "list_projects", "retry_job", "video_info",
        ]))

    def test_setup_reports_keys_as_flags_only(self):
        setup = self.answers["check_setup"]
        self.assertEqual(setup["api_keys_set"], {"openai": False, "gemini": True, "groq": True})
        self.assertNotIn("AIz", str(setup))

    def test_luna_errors_reach_the_agent(self):
        self.assertIn("Only YouTube", self.answers["rejected"]["error"])

    def test_job_finishes_and_clips_are_saved(self):
        self.assertEqual(self.answers["job_status"]["status"], "completed")
        clips = self.answers["get_clips"]["clips"]
        self.assertEqual([c["filename"] for c in clips], ["short_1.mp4", "short_2.mp4"])
        for clip in clips:
            self.assertTrue(clip["download_url"].startswith("http://127.0.0.1:"))
            with open(clip["local_path"], "rb") as f:
                self.assertEqual(f.read(), b"fake mp4 bytes")
            self.assertEqual(os.path.dirname(clip["local_path"]), self.folder)


class TestUnreachableLuna(unittest.TestCase):
    def test_says_how_to_fix_it(self):
        from luna import mcp_server

        os.environ["LUNA_URL"] = "http://127.0.0.1:9"
        try:
            with self.assertRaises(mcp_server.ToolError) as ctx:
                mcp_server._call("GET", "/api/settings", timeout=5)
        finally:
            del os.environ["LUNA_URL"]
        self.assertIn("Cannot reach Luna", str(ctx.exception))
        self.assertIn("LUNA_URL", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
