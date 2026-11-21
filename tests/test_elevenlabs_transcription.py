import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from luna.app import _missing_ai_clip_api_keys, app
from luna.clipper import transcriber

WORDS = [
    {"text": "Halo", "start": 0.0, "end": 0.4, "type": "word"},
    {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing"},
    {"text": "semua.", "start": 0.5, "end": 1.0, "type": "word"},
    {"text": " ", "start": 1.0, "end": 1.0, "type": "spacing"},
    {"text": "(laughter)", "start": 1.0, "end": 1.5, "type": "audio_event"},
    {"text": "Ini", "start": 1.6, "end": 1.9, "type": "word"},
    {"text": " ", "start": 1.9, "end": 1.9, "type": "spacing"},
    {"text": "tes", "start": 1.9, "end": 2.2, "type": "word"},
    {"text": " ", "start": 2.2, "end": 4.0, "type": "spacing"},
    {"text": "lagi", "start": 4.0, "end": 4.4, "type": "word"},
]


class _ElevenLabs(BaseHTTPRequestHandler):
    """Minimal stand-in for the ElevenLabs API that records what it receives."""

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_error(self):
        key = self.headers.get("xi-api-key")
        if key == "good-key":
            return None
        if key == "scoped-key" and self.path == "/v1/models":
            return {"detail": {"status": "missing_permissions", "message": "missing models_read"}}
        return {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}

    def do_GET(self):
        self.server.requests.append(("GET", self.path))
        error = self._auth_error()
        self._send(401, error) if error else self._send(200, [{"model_id": "eleven_v3"}])

    def do_POST(self):
        self.server.requests.append(("POST", self.path))
        self.server.body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        error = self._auth_error()
        if error:
            self._send(401, error)
            return
        self._send(200, {"language_code": "id", "language_probability": 0.99, "text": "Halo", "words": WORDS})

    def log_message(self, *args):
        pass


class TestElevenLabsTranscription(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), _ElevenLabs)
        self.server.requests = []
        self.server.body = b""
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        env = patch.dict(os.environ, {
            "ELEVENLABS_BASE_URL": f"http://127.0.0.1:{self.server.server_port}",
            "ELEVENLABS_API_KEY": "good-key",
            "ELEVENLABS_STT_MODEL": "",
        })
        env.start()
        self.addCleanup(env.stop)
        for name, replacement in (
            ("_extract_compressed_audio", lambda _src, out: Path(out).write_bytes(b"audio")),
            ("_probe_media_duration", lambda _path: 5.0),
        ):
            stub = patch.object(transcriber, name, replacement)
            stub.start()
            self.addCleanup(stub.stop)

    def test_words_are_grouped_at_punctuation_and_pauses(self):
        self.assertEqual(transcriber._elevenlabs_words_to_segments(WORDS), [
            {"start": 0.0, "end": 1.0, "text": "Halo semua."},
            {"start": 1.6, "end": 2.2, "text": "Ini tes"},
            {"start": 4.0, "end": 4.4, "text": "lagi"},
        ])

    def test_long_speech_without_punctuation_is_capped(self):
        words = []
        for i in range(60):
            words.append({"text": f"w{i}", "start": i * 0.5, "end": i * 0.5 + 0.4, "type": "word"})
            words.append({"text": " ", "type": "spacing"})
        segments = transcriber._elevenlabs_words_to_segments(words)
        self.assertGreater(len(segments), 1)
        for seg in segments:
            self.assertLessEqual(seg["end"] - seg["start"], transcriber.ELEVENLABS_SEGMENT_MAX_SECONDS)
        self.assertEqual(" ".join(s["text"] for s in segments).split(), [f"w{i}" for i in range(60)])

    def test_transcription_posts_audio_and_returns_segments(self):
        result = transcriber._transcribe_local_elevenlabs("video.mp4", language="id")
        self.assertEqual(self.server.requests, [("POST", "/v1/speech-to-text")])
        self.assertIn(b"scribe_v3", self.server.body)
        self.assertIn(b'name="language_code"', self.server.body)
        self.assertEqual(result["duration"], 5.0)
        self.assertEqual([s["text"] for s in result["segments"]], ["Halo semua.", "Ini tes", "lagi"])

    def test_rejected_key_raises_without_echoing_it(self):
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "bad-key"}):
            with self.assertRaises(RuntimeError) as ctx:
                transcriber._transcribe_local_elevenlabs("video.mp4")
        self.assertIn("401", str(ctx.exception))
        self.assertIn("Invalid API key", str(ctx.exception))
        self.assertNotIn("bad-key", str(ctx.exception))

    def test_missing_key_fails_before_any_upload(self):
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}):
            with self.assertRaises(RuntimeError):
                transcriber._transcribe_local_elevenlabs("video.mp4")
        self.assertEqual(self.server.requests, [])

    def test_dispatch_uses_elevenlabs_when_selected(self):
        with patch.dict(os.environ, {"LOCAL_TRANSCRIBE_PROVIDER": "elevenlabs"}), \
                patch.object(transcriber, "_try_fetch_native_youtube_subtitles", return_value=None), \
                patch.object(transcriber, "_write_srt_cache", return_value="x.srt"), \
                tempfile.TemporaryDirectory() as tmp:
            result = transcriber.transcribe_local(os.path.join(tmp, "v.mp4"), video_url="https://example.test/v")
        self.assertEqual(result["provider"], "ElevenLabs Scribe")
        self.assertEqual(len(result["segments"]), 3)

    def test_key_test_accepts_full_and_scoped_keys_only(self):
        client = TestClient(app)
        verdicts = {
            key: client.post("/api/settings/test-key", json={"provider": "elevenlabs", "api_key": key}).json()["valid"]
            for key in ("good-key", "scoped-key", "bad-key")
        }
        self.assertEqual(verdicts, {"good-key": True, "scoped-key": True, "bad-key": False})

    def test_settings_save_provider_and_key(self):
        client = TestClient(app)
        with tempfile.TemporaryDirectory() as tmp, patch("luna.app.BASE_DIR", tmp), \
                patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}):
            saved = client.post("/api/settings", json={
                "transcribe_provider": "elevenlabs", "elevenlabs_api_key": "sk_live_example_key_1234"})
            self.assertEqual(saved.status_code, 200)
            data = client.get("/api/settings").json()
            with open(os.path.join(tmp, ".env"), encoding="utf-8") as f:
                env_text = f.read()
        self.assertEqual(data["transcribe_provider"], "elevenlabs")
        self.assertTrue(data["has_elevenlabs_api_key"])
        self.assertEqual(data["elevenlabs_api_key"], "sk_...1234")
        self.assertEqual(data["elevenlabs_model"], "scribe_v3")
        self.assertIn("LOCAL_TRANSCRIBE_PROVIDER=elevenlabs", env_text)
        self.assertIn("ELEVENLABS_API_KEY=sk_live_example_key_1234", env_text)

    def test_ai_clips_report_a_missing_elevenlabs_key(self):
        env = {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "g", "LOCAL_TRANSCRIBE_PROVIDER": "elevenlabs",
               "ELEVENLABS_API_KEY": ""}
        with patch.dict(os.environ, env):
            self.assertEqual(
                _missing_ai_clip_api_keys(),
                "ElevenLabs API key is required for audio transcription in AI Short Clips.",
            )


if __name__ == "__main__":
    unittest.main()
