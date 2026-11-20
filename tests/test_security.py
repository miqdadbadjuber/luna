import os
import socket
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from luna.app import _resolve_safe_redirect, app, detect_platform, external_url_problem


def _resolves_to(address):
    return lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]


class TestHostAllowlist(unittest.TestCase):
    def test_foreign_host_header_is_rejected(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-secret-value"}):
            res = TestClient(app).get("/api/settings", headers={"Host": "evil.example"})
        self.assertEqual(res.status_code, 400)
        self.assertNotIn("secret", res.text)

    def test_localhost_is_allowed(self):
        for host in ("localhost:8000", "127.0.0.1:8000"):
            res = TestClient(app).get("/api/settings", headers={"Host": host})
            self.assertEqual(res.status_code, 200, host)


class TestUrlFilter(unittest.TestCase):
    def test_platform_comes_from_the_host_name(self):
        self.assertEqual(detect_platform("https://m.youtube.com/watch?v=abc"), "youtube")
        self.assertEqual(detect_platform("https://vm.tiktok.com/x"), "tiktok")
        self.assertEqual(detect_platform("https://evil.example/?u=youtube.com"), "unknown")
        self.assertEqual(detect_platform("https://youtube.com.evil.example/"), "unknown")

    def test_unsupported_sites_are_rejected_before_resolving(self):
        with patch("socket.getaddrinfo") as resolve:
            self.assertIsNotNone(external_url_problem("http://localtest.me:8000/"))
            self.assertIsNotNone(external_url_problem("http://127.0.0.1/"))
        resolve.assert_not_called()

    def test_supported_host_resolving_to_a_private_address_is_rejected(self):
        for address in ("127.0.0.1", "10.0.0.5", "169.254.169.254"):
            with patch("socket.getaddrinfo", _resolves_to(address)):
                self.assertEqual(external_url_problem("https://youtube.com/watch?v=abc"), "That address is not allowed.")

    def test_supported_public_url_passes(self):
        with patch("socket.getaddrinfo", _resolves_to("142.250.4.136")):
            self.assertIsNone(external_url_problem("https://www.youtube.com/watch?v=abc"))


class TestOriginCsrfProtection(unittest.TestCase):
    def test_cross_origin_mutation_is_rejected(self):
        client = TestClient(app)
        with patch("luna.app._open_windows_explorer") as mock_open, \
                patch("subprocess.Popen") as mock_popen:
            for headers in (
                {"Origin": "https://evil.example"},
                {"Origin": "null"},
                {"Sec-Fetch-Site": "cross-site"},
            ):
                res = client.post("/api/vault/open-folder", headers=headers)
                self.assertEqual(res.status_code, 403, headers)
            mock_open.assert_not_called()
            mock_popen.assert_not_called()

    def test_same_origin_and_cli_mutations_are_allowed(self):
        client = TestClient(app)
        for headers in (
            {"Origin": "http://127.0.0.1:8000"},
            {"Origin": "http://localhost:8000"},
            {},
        ):
            res = client.post("/api/settings/check-system", headers=headers)
            self.assertEqual(res.status_code, 200, headers)


class TestRedirectSsrfAndFrontendHygiene(unittest.TestCase):
    def test_tiktok_redirect_ssrf_is_blocked_before_following(self):
        hop1 = MagicMock()
        hop1.status_code = 302
        hop1.headers = {"location": "http://127.0.0.1:8000/api/settings"}

        with patch("socket.getaddrinfo", _resolves_to("23.50.1.10")), \
                patch("requests.get", return_value=hop1) as mock_get:
            resolved = _resolve_safe_redirect("https://vt.tiktok.com/ZS123/", {"User-Agent": "test"})

        self.assertEqual(resolved, "https://vt.tiktok.com/ZS123/")
        mock_get.assert_called_once()
        self.assertIs(mock_get.call_args.kwargs.get("allow_redirects"), False)

    def test_app_js_escapes_errors_and_sanitizes_download_urls(self):
        app_js = Path(__file__).resolve().parents[1] / "luna" / "assets" / "ui" / "app.js"
        src = app_js.read_text(encoding="utf-8")
        self.assertNotIn("✗ ${errMsg}", src)
        self.assertIn("✗ ${escapeHtml(errMsg)}", src)
        self.assertNotIn('href="${downloadUrl}"', src)
        self.assertIn('href="${escapeHtml(encodeMediaUrl(downloadUrl))}"', src)

    def test_requirements_pins_patched_curl_cffi(self):
        req_file = Path(__file__).resolve().parents[1] / "requirements.txt"
        lines = [ln.strip() for ln in req_file.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
        cffi_line = next((ln for ln in lines if ln.lower().startswith("curl-cffi")), "")
        self.assertTrue(cffi_line, "curl-cffi missing from requirements.txt")
        ver_str = cffi_line.split("==")[-1].split(">=")[-1]
        parts = tuple(int(p) for p in ver_str.split(".")[:3])
        self.assertGreaterEqual(parts, (0, 15, 0))


if __name__ == "__main__":
    unittest.main()
