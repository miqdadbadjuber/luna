"""Browser smoke test: the real page and server, with the job endpoints stubbed.

Run with: python -m unittest discover -s tests_browser -t . -p 'browser_*.py'
(The file name keeps it out of the plain unit test run, which has no browser.)
Needs: pip install playwright && python -m playwright install --with-deps chromium
"""
import os
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import uvicorn
from playwright.sync_api import expect, sync_playwright

import luna.app as app_module

JOB = "deadbeef"
URL = "https://www.youtube.com/watch?v=abcdefghijk"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BrowserSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {"MEDIA_STORAGE_DIR": cls.tmp.name})
        cls.base = patch.object(app_module, "BASE_DIR", cls.tmp.name)
        cls.env.start()
        cls.base.start()
        port = _free_port()
        cls.origin = f"http://127.0.0.1:{port}"
        cls.server = uvicorn.Server(uvicorn.Config(app_module.app, host="127.0.0.1", port=port, log_level="warning"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 20
        while not cls.server.started:
            if time.time() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.1)
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.should_exit = True
        cls.thread.join(10)
        cls.base.stop()
        cls.env.stop()
        cls.tmp.cleanup()

    def setUp(self):
        self.page = self.browser.new_page()
        # The page head loads Tailwind and lucide from CDNs, which are sometimes slow.
        self.page.set_default_navigation_timeout(90000)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.addCleanup(self.page.close)

    def _stub_settings(self, *, has_gemini=True, has_groq=True, has_openai=False, studio_bg="obsidian"):
        payload = {
            "llm_provider": "",
            "transcribe_provider": "groq",
            "clip_language": "id",
            "studio_background": studio_bg,
            "openai_api_key": "",
            "openai_api_key_set": has_openai,
            "has_openai_api_key": has_openai,
            "openai_base_url": "https://api.openai.com/v1",
            "openai_model": "gpt-4o-mini",
            "gemini_api_key": "••••1234" if has_gemini else "",
            "has_gemini_api_key": has_gemini,
            "gemini_model": "gemini-3.8-flash",
            "groq_api_key": "••••5678" if has_groq else "",
            "has_groq_api_key": has_groq,
            "groq_model": "whisper-large-v3-turbo",
            "storage_dir": self.tmp.name,
            "status": {
                "ffmpeg": True, "ytdlp": "2026", "js_runtime": False,
                "opencv": True, "storage": True, "cookies": {"exists": False},
            },
        }

        def handle(route):
            if route.request.method == "GET":
                route.fulfill(json=payload)
            else:
                route.continue_()

        self.page.route("**/api/settings", handle)

    def _stub_job(self, final_status):
        """Stub the job API: the job runs for one poll, then ends with final_status."""
        polls = {"n": 0}

        def status(route):
            polls["n"] += 1
            body = {"id": JOB, "action": "type_yt_video", "status": "processing", "stage": "downloading",
                    "progress": 40.0, "logs": [], "results": [], "retryable": False}
            if polls["n"] > 1:
                body.update(final_status)
            route.fulfill(json=body)

        self._stub_settings(has_gemini=True, has_groq=True)
        self.page.route("**/api/info", lambda r: r.fulfill(json={
            "title": "Smoke test video", "thumbnail": "", "duration": 60, "platform": "youtube"}))
        self.page.route("**/api/check-transcript*", lambda r: r.fulfill(json={"has_transcript": True}))
        self.page.route("**/api/process", lambda r: r.fulfill(json={"job_id": JOB, "status": "queued"}))
        self.page.route(f"**/api/status/{JOB}", status)

    def _open(self):
        # "load" waits on CDN fonts and the WebGL background; the app is usable once its script ran.
        self.page.goto(self.origin + "/", wait_until="domcontentloaded")
        self.page.wait_for_function("typeof triggerAction === 'function' && typeof saveSettings === 'function'")

    def _start_job(self):
        self._open()
        self.page.fill("#mainUrlInput", URL)
        # The page looks the URL up first; clicking before that lands does nothing.
        self.page.get_by_text("Smoke test video").first.wait_for()
        self.page.click("#mainActionBtn")
        self.page.click("#workspaceConfirmModal button:has-text('Start')")
        proceed = self.page.locator("#confirmModalProceedBtn")
        try:
            proceed.wait_for(state="visible", timeout=1500)
            proceed.click()
        except Exception:
            pass  # only some actions ask for confirmation

    def test_settings_save_writes_env(self):
        self._open()
        # Opening the tab reloads settings into the form, so change it after that lands.
        with self.page.expect_response(lambda r: r.url.endswith("/api/settings") and r.request.method == "GET"):
            self.page.click("#btnNavSettings")
        self.page.wait_for_timeout(300)
        self.page.click("#transcribeTrigger")
        self.page.click("#transcribeMenu [data-value='gemini']")
        self.page.click("#btnToastSaveSettings")
        expect(self.page.locator("#toastMessage")).to_contain_text("Settings saved")
        with open(os.path.join(self.tmp.name, ".env"), encoding="utf-8") as f:
            self.assertIn("LOCAL_TRANSCRIBE_PROVIDER=gemini", f.read())
        self.assertEqual(self.errors, [])

    def test_a_completed_job_shows_its_result(self):
        self._stub_job({"status": "completed", "stage": "done", "progress": 100.0, "workspace_name": "Workspace 01",
                        "results": [{"type": "video", "title": "clip.mp4", "filename": "clip.mp4",
                                     "url": f"/output/{JOB}/clip.mp4",
                                     "download_url": f"/api/download-file/{JOB}/clip.mp4"}]})
        self._start_job()
        expect(self.page.locator("#progressCompletionBanner")).to_be_visible(timeout=15000)
        self.assertEqual(self.errors, [])

    def test_a_failed_job_says_so(self):
        self._stub_job({"status": "failed", "error": "The video could not be found."})
        self._start_job()
        expect(self.page.locator("#noticeModalHeading")).to_have_text("Processing failed", timeout=15000)
        expect(self.page.locator("#noticeModalDesc")).to_contain_text("could not be found")
        expect(self.page.locator("#progressCompletionBanner")).to_be_hidden()
        self.assertEqual(self.errors, [])

    def test_qa1_preflight_blocks_missing_api_keys_and_links_to_settings(self):
        self._stub_settings(has_gemini=False, has_groq=False)
        self._open()
        self.page.fill("#mainUrlInput", URL)
        self.page.click("#mainActionBtn")
        link = self.page.locator(".luna-toast-link")
        expect(link).to_be_visible(timeout=5000)
        expect(self.page.locator("#toastMessage")).to_contain_text("Gemini")
        expect(self.page.locator("#toastMessage")).to_contain_text("Groq")
        expect(self.page.locator("#workspaceConfirmModal")).to_be_hidden()
        link.click()
        expect(self.page.locator("#section-settings")).to_be_visible(timeout=5000)
        self.assertEqual(self.errors, [])

    def test_qa2_unsaved_settings_leave_guard_and_api_key_autosave(self):
        self._stub_settings(has_gemini=False, has_groq=False)
        self.page.route("**/api/settings/test-key", lambda r: r.fulfill(json={"valid": True, "message": "OK"}))
        self._open()
        self.page.click("#btnNavSettings")
        expect(self.page.locator("#section-settings")).to_be_visible(timeout=5000)
        self.page.fill("#inputGemini", "AIzaSyTestAutoSave1234")
        # Attempting to leave Settings while dirty must stay on Settings and warn
        self.page.click("#tabBtnStudio")
        expect(self.page.locator("#section-settings")).to_be_visible()
        expect(self.page.locator("#toastMessage")).to_contain_text("Save or cancel")
        # Valid Test Connection auto-saves key and unlocks navigation
        self.page.locator("button:has-text('Test Connection')").first.click()
        expect(self.page.locator("#inputGemini")).to_be_disabled(timeout=5000)
        self.page.click("#tabBtnStudio")
        expect(self.page.locator("#section-settings")).to_be_hidden(timeout=5000)
        self.assertEqual(self.errors, [])

    def test_qa3_check_for_updates_modal_states_and_spinner_cleanup(self):
        state = {"available": True}

        def handle_check(route):
            if state["available"]:
                route.fulfill(json={
                    "update_available": True, "current_short_sha": "1111111",
                    "latest_short_sha": "2222222", "latest_message": "QA update test", "busy_jobs": False,
                })
            else:
                route.fulfill(json={
                    "update_available": False, "current_short_sha": "2222222",
                    "latest_short_sha": "2222222", "latest_message": "Up to date", "busy_jobs": False,
                })

        self.page.route("**/api/system/check-update", handle_check)
        self._open()
        self.page.click("#btnNavSettings")
        expect(self.page.locator("#btnCheckUpdates")).to_be_visible(timeout=5000)
        # Update Available state
        self.page.click("#btnCheckUpdates")
        expect(self.page.locator("#updateModalHeading")).to_have_text("Update Available", timeout=5000)
        expect(self.page.locator("#updateModalActionBtn")).to_be_visible()
        self.page.click("#updateModalLaterBtn")
        expect(self.page.locator("#checkUpdatesSpinner")).to_be_hidden()
        expect(self.page.locator("#checkUpdatesIcon")).to_be_visible()
        # Up to date state
        state["available"] = False
        self.page.click("#btnCheckUpdates")
        expect(self.page.locator("#updateModalHeading")).to_have_text("You're up to date", timeout=5000)
        self.page.click("#updateModalOkBtn")
        expect(self.page.locator("#checkUpdatesSpinner")).to_be_hidden()
        self.assertEqual(self.errors, [])

    def test_qa4_studio_background_preset_autosaves_without_leave_guard(self):
        self._open()
        self.page.click("#btnNavSettings")
        card = self.page.locator("#studioBackgroundGrid [data-bg-option='crimson-horizon']")
        expect(card).to_be_visible(timeout=5000)
        with self.page.expect_response(lambda r: r.url.endswith("/api/settings") and r.request.method == "POST"):
            card.click()
        expect(self.page.locator("#studioBackgroundContainer")).to_have_attribute("data-bg-id", "crimson-horizon")
        # Auto-saved preset must not block leaving Settings
        self.page.click("#tabBtnStudio")
        expect(self.page.locator("#section-settings")).to_be_hidden(timeout=5000)
        self.assertEqual(self.errors, [])

    def test_qa5_url_validation_and_shorts_and_16_9_lock_rules(self):
        self._open()
        # Unsupported domain rejected upfront before Workspace modal
        self.page.fill("#mainUrlInput", "https://example.com/not-supported")
        self.page.click("#mainActionBtn")
        expect(self.page.locator("#noticeModalHeading")).to_have_text("Invalid URL", timeout=5000)
        self.page.click("#noticeModal button:has-text('OK')")
        # 16:9 Wide locks Face Track pill
        self.page.click("#aspectRatioDropdownBtn")
        self.page.click("#aspectRatioMenu [data-ratio='16:9']")
        expect(self.page.locator("#faceDetectDropdownBtn")).to_be_disabled()
        # YouTube Shorts URL switches away from AI Short Clips and disables Shorts-locked items
        self.page.fill("#mainUrlInput", "https://www.youtube.com/shorts/abcdefghijk")
        expect(self.page.locator("#currentSubFeatureLabel")).not_to_have_text("AI Short Clips", timeout=5000)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
