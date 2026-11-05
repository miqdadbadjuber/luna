import os
import socket
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from luna.app import app, detect_platform, external_url_problem


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


if __name__ == "__main__":
    unittest.main()
