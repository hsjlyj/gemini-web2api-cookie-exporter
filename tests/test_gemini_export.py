from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gemini_export._common import (
    GEMINI_URL,
    MINIMUM_COOKIE_NAMES,
    extract_auth_user,
    extract_gemini_bl,
    extract_xsrf_token,
    read_json_object,
    select_cookie_string,
    update_config,
    write_json_file,
)


class TestGeminiExport(unittest.TestCase):
    def test_extract_xsrf_token(self):
        html = '"SNlM0e":"xsrf-demo","build":"boq_assistant-bard-web-server_20260714.01_p0"'
        self.assertEqual(extract_xsrf_token(html), "xsrf-demo")

    def test_extract_gemini_bl(self):
        html = '"SNlM0e":"xsrf","build":"boq_assistant-bard-web-server_20260714.01_p0"'
        self.assertEqual(extract_gemini_bl(html), "boq_assistant-bard-web-server_20260714.01_p0")

    def test_extract_auth_user(self):
        self.assertEqual(extract_auth_user("https://gemini.google.com/u/1/app/abc"), "1")
        self.assertIsNone(extract_auth_user("https://gemini.google.com/app"))

    def test_select_cookie_string(self):
        cookies = [
            {"name": "SAPISID", "value": "secret-sapisid", "domain": ".google.com"},
            {"name": "SID", "value": "secret-sid", "domain": ".google.com"},
            {"name": "irrelevant", "value": "ignored", "domain": ".google.com"},
        ]
        cookie, names = select_cookie_string(cookies)
        self.assertTrue(cookie.startswith("SID=secret-sid; SAPISID=secret-sapisid"))
        self.assertEqual(names, {"SID", "SAPISID"})

    def test_write_read_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "gemini-export.json"
            payload = {"cookie_file": "cookie.txt", "auth_user": "0"}
            write_json_file(target, payload)
            self.assertTrue(target.exists())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(read_json_object(target), payload)

    def test_update_config_merges_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            write_json_file(target, {"cookie_file": "cookie.txt"})
            update_config(target, {"xsrf_token": "token"})
            self.assertEqual(
                read_json_object(target),
                {"cookie_file": "cookie.txt", "xsrf_token": "token"},
            )

    def test_select_cookie_string_with_playwright_style_cookies(self):
        cookies = [
            {"name": "SAPISID", "value": "secret-sapisid", "domain": ".google.com", "httpOnly": True},
            {"name": "__Secure-1PSID", "value": "secret-sid", "domain": ".google.com", "httpOnly": True},
            {"name": "NID", "value": "ignore-me", "domain": ".google.com"},
        ]
        cookie, names = select_cookie_string(cookies)
        self.assertEqual(names, {"SAPISID", "__Secure-1PSID"})
        self.assertIn("SAPISID=secret-sapisid", cookie)
        self.assertIn("__Secure-1PSID=secret-sid", cookie)


if __name__ == "__main__":
    unittest.main()
