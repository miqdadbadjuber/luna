import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from luna.app import app
from luna.clipper import transcriber
from luna.clipper.llm import call_llm


class _Provider(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible endpoint that records what it receives."""

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        ok = self.headers.get("Authorization") == "Bearer good-key"
        self.server.requests.append(self.path)
        self._send(200 if ok else 401, {"data": [
            {"id": "z-chat"}, {"id": "a-chat"}, {"id": "text-embedding-3"}, {"id": "whisper-1"},
        ]})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.requests.append(self.path)
        if self.path.endswith("/chat/completions"):
            model = json.loads(raw)["model"]
            self._send(200, {
                "id": "x", "object": "chat.completion", "created": 0, "model": model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": f"from {model}"}}],
            })
        else:
            self.server.transcribe_body = raw
            self._send(200, self.server.transcript)

    def log_message(self, *args):
        pass


class TestOpenAICompatible(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), _Provider)
        self.server.requests = []
        self.server.transcript = {
            "text": "hello", "duration": 3.0,
            "segments": [{"id": 0, "start": 0.5, "end": 3.0, "text": " hello "}],
        }
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        env = patch.dict(os.environ, {
            "OPENAI_API_KEY": "good-key",
            "OPENAI_BASE_URL": self.base_url,
            "OPENAI_MODEL": "chat-model",
            "GROQ_API_KEY": "good-key",
        })
        env.start()
        self.addCleanup(env.stop)
        extract = patch.object(
            transcriber, "_extract_compressed_audio",
            lambda _src, out: Path(out).write_bytes(b"audio"),
        )
        extract.start()
        self.addCleanup(extract.stop)

    def test_llm_uses_configured_endpoint_and_model(self):
        os.environ.pop("LLM_PROVIDER", None)
        self.assertEqual(call_llm("hi"), "from chat-model")
        self.assertEqual(self.server.requests, ["/v1/chat/completions"])

    def test_blank_base_url_falls_back_to_default(self):
        from luna.clipper.config import DEFAULT_OPENAI_BASE_URL, openai_base_url
        with patch.dict(os.environ, {"OPENAI_BASE_URL": ""}):
            self.assertEqual(openai_base_url(), DEFAULT_OPENAI_BASE_URL)

    def test_groq_transcription_returns_segments(self):
        with patch("luna.clipper.config.GROQ_BASE_URL", self.base_url):
            result = transcriber._transcribe_local_groq("video.mp4")
        self.assertEqual(result["segments"], [{"start": 0.5, "end": 3.0, "text": "hello"}])
        self.assertEqual(result["duration"], 3.0)
        self.assertEqual(self.server.requests, ["/v1/audio/transcriptions"])
        self.assertIn(b"verbose_json", self.server.transcribe_body)

    def test_settings_save_and_key_test_use_a_temp_env_file(self):
        client = TestClient(app)
        with tempfile.TemporaryDirectory() as tmp, patch("luna.app.BASE_DIR", tmp):
            bad = client.post("/api/settings/test-key", json={
                "provider": "openai", "api_key": "bad-key", "base_url": self.base_url})
            self.assertFalse(bad.json()["valid"])
            self.assertFalse(os.path.exists(os.path.join(tmp, ".env")))

            good = client.post("/api/settings/test-key", json={
                "provider": "openai", "api_key": "good-key", "base_url": self.base_url})
            self.assertTrue(good.json()["valid"])
            self.assertFalse(good.json().get("saved", False))

            saved = client.post("/api/settings", json={
                "openai_api_key": "good-key",
                "openai_base_url": self.base_url,
                "openai_model": "new-model",
            })
            self.assertEqual(saved.status_code, 200)
            with open(os.path.join(tmp, ".env"), encoding="utf-8") as f:
                content = f.read()
        self.assertIn(f"OPENAI_BASE_URL={self.base_url}", content)
        self.assertIn("OPENAI_MODEL=new-model", content)
        self.assertEqual(client.get("/api/settings").json()["openai_model"], "new-model")

    def test_settings_reject_a_non_http_base_url(self):
        res = TestClient(app).post("/api/settings", json={"openai_base_url": "file:///etc/passwd"})
        self.assertEqual(res.status_code, 400)

    def test_highlight_retries_report_the_last_error(self):
        from luna.clipper.highlights import call_highlight_api

        def failing_llm(_prompt):
            raise ValueError("provider down")

        with patch("luna.clipper.highlights.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "provider down"):
                call_highlight_api("prompt", llm_fn=failing_llm)
        self.assertEqual(sleep.call_count, 2)

    def test_gemini_is_used_when_selected_or_when_it_is_the_only_key(self):
        from luna.clipper import llm
        from luna.clipper.config import llm_provider

        with patch.object(llm, "call_gemini_llm", return_value="from gemini"):
            with patch.dict(os.environ, {"LLM_PROVIDER": "gemini"}):
                self.assertEqual(call_llm("hi"), "from gemini")
            with patch.dict(os.environ, {"LLM_PROVIDER": "", "OPENAI_API_KEY": "", "GEMINI_API_KEY": "g"}):
                self.assertEqual(llm_provider(), "gemini")
            with patch.dict(os.environ, {"LLM_PROVIDER": "", "GEMINI_API_KEY": "g"}):
                self.assertEqual(llm_provider(), "openai")

    def test_unknown_provider_is_rejected(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "nope"}):
            with self.assertRaisesRegex(RuntimeError, "Unknown LLM_PROVIDER"):
                call_llm("hi")

    def test_provider_settings_are_saved_and_apply_to_the_next_job(self):
        from luna.clipper import config

        client = TestClient(app)
        with tempfile.TemporaryDirectory() as tmp, patch("luna.app.BASE_DIR", tmp), patch.dict(os.environ):
            res = client.post("/api/settings", json={"llm_provider": "gemini", "transcribe_provider": "whisper"})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(config.llm_provider(), "gemini")
            self.assertEqual(config.transcribe_provider(), "whisper")
            self.assertEqual(config.transcribe_provider_label(), "Faster-Whisper Local")
            data = client.get("/api/settings").json()
            self.assertEqual((data["llm_provider"], data["transcribe_provider"]), ("gemini", "whisper"))

            client.post("/api/settings", json={"llm_provider": ""})
            self.assertEqual(client.get("/api/settings").json()["llm_provider"], "")
            with open(os.path.join(tmp, ".env"), encoding="utf-8") as f:
                self.assertIn("LOCAL_TRANSCRIBE_PROVIDER=whisper", f.read())

    def test_unknown_provider_settings_are_rejected(self):
        client = TestClient(app)
        with patch("luna.app._update_env_file") as save:
            self.assertEqual(client.post("/api/settings", json={"llm_provider": "nope"}).status_code, 400)
            self.assertEqual(client.post("/api/settings", json={"transcribe_provider": ""}).status_code, 400)
        save.assert_not_called()

    def test_transcription_dispatch_follows_the_setting(self):
        with patch.dict(os.environ, {"LOCAL_TRANSCRIBE_PROVIDER": "whisper"}), \
                patch.object(transcriber, "_transcribe_local_whisper", return_value={"segments": [], "duration": 0}) as run, \
                patch.object(transcriber, "_try_fetch_native_youtube_subtitles", return_value=None), \
                patch.object(transcriber, "_write_srt_cache", return_value="x.srt"), \
                patch.object(transcriber, "_load_srt_cache", return_value=None), \
                tempfile.TemporaryDirectory() as tmp:
            result = transcriber.transcribe_local(os.path.join(tmp, "v.mp4"), video_url="https://example.test/v")
        run.assert_called_once()
        self.assertEqual(result["provider"], "Faster-Whisper Local")

    def test_model_list_keeps_chat_models_sorted(self):
        res = TestClient(app).post("/api/settings/openai-models", json={"api_key": "good-key", "base_url": self.base_url})
        self.assertEqual(res.json(), {"models": ["a-chat", "z-chat"]})

    def test_model_list_reports_a_rejected_key_without_echoing_it(self):
        res = TestClient(app).post("/api/settings/openai-models", json={"api_key": "bad-key", "base_url": self.base_url})
        self.assertEqual(res.status_code, 502)
        self.assertNotIn("bad-key", res.text)

    def test_model_list_never_sends_the_saved_key_to_another_url(self):
        env = {"OPENAI_API_KEY": "good-key", "OPENAI_BASE_URL": "https://api.example.test/v1"}
        with patch.dict(os.environ, env):
            res = TestClient(app).post("/api/settings/openai-models", json={"api_key": " ", "base_url": self.base_url})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.server.requests, [])

    def test_key_test_never_sends_the_saved_key_to_another_url(self):
        env = {"OPENAI_API_KEY": "good-key", "OPENAI_BASE_URL": "https://api.example.test/v1"}
        with patch.dict(os.environ, env):
            res = TestClient(app).post("/api/settings/test-key", json={"provider": "openai", "base_url": self.base_url})
        self.assertFalse(res.json()["valid"])
        self.assertEqual(self.server.requests, [])

    def test_key_test_uses_the_saved_key_for_the_saved_url(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "good-key", "OPENAI_BASE_URL": self.base_url}):
            res = TestClient(app).post("/api/settings/test-key", json={"provider": "openai", "base_url": self.base_url})
        self.assertTrue(res.json()["valid"])

    def test_model_list_uses_the_saved_key_for_the_saved_url(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "good-key", "OPENAI_BASE_URL": self.base_url}):
            res = TestClient(app).post("/api/settings/openai-models", json={"base_url": self.base_url + "/"})
        self.assertEqual(res.json(), {"models": ["a-chat", "z-chat"]})


if __name__ == "__main__":
    unittest.main()
