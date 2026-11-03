from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gemini_export._common import (
    AUTH_COOKIE_NAMES,
    GEMINI_URL,
    MINIMUM_COOKIE_NAMES,
    PREFERRED_COOKIE_ORDER,
    add_common_export_args,
    build_launch_args,
    extract_auth_user,
    extract_build_info,
    extract_gemini_bl,
    extract_xsrf_token,
    find_browser,
    read_json_object,
    select_cookie_string,
    update_config,
    write_json_file,
    write_secret_file,
)


class TestExtractXsrfToken(unittest.TestCase):
    def test_extracts_from_json_style(self):
        html = '"SNlM0e":"xsrf-demo","build":"boq"'
        self.assertEqual(extract_xsrf_token(html), "xsrf-demo")

    def test_extracts_from_comma_style(self):
        html = '"SNlM0e","xsrf-value-here"'
        self.assertEqual(extract_xsrf_token(html), "xsrf-value-here")

    def test_extracts_from_escaped_style(self):
        html = r"SNlM0e\'=\'abc123"
        self.assertEqual(extract_xsrf_token(html), "abc123")

    def test_returns_none_when_missing(self):
        self.assertIsNone(extract_xsrf_token("<html>no token here</html>"))

    def test_returns_none_for_empty(self):
        self.assertIsNone(extract_xsrf_token(""))


class TestExtractGeminiBl(unittest.TestCase):
    def test_extracts_build_label(self):
        html = '"build":"boq_assistant-bard-web-server_20260714.01_p0"'
        self.assertEqual(
            extract_gemini_bl(html),
            "boq_assistant-bard-web-server_20260714.01_p0",
        )

    def test_returns_longest_match(self):
        html = "boq_short boq_assistant-bard-web-server_20260714.01_p0"
        self.assertEqual(
            extract_gemini_bl(html),
            "boq_assistant-bard-web-server_20260714.01_p0",
        )

    def test_returns_none_when_missing(self):
        self.assertIsNone(extract_gemini_bl("no build here"))


class TestExtractAuthUser(unittest.TestCase):
    def test_extracts_user_id(self):
        self.assertEqual(
            extract_auth_user("https://gemini.google.com/u/42/app/abc"), "42"
        )

    def test_handles_trailing_slash(self):
        self.assertEqual(
            extract_auth_user("https://gemini.google.com/u/1/"), "1"
        )

    def test_returns_none_for_non_user_url(self):
        self.assertIsNone(
            extract_auth_user("https://gemini.google.com/app")
        )

    def test_returns_none_for_empty(self):
        self.assertIsNone(extract_auth_user(""))


class TestExtractBuildInfo(unittest.TestCase):
    def test_extracts_both_fields(self):
        html = '"SNlM0e":"xsrf","build":"boq_assistant-bard-web-server_20260714.01_p0"'
        info = extract_build_info(html)
        self.assertEqual(info["xsrf_token"], "xsrf")
        self.assertEqual(info["build_label"], "boq_assistant-bard-web-server_20260714.01_p0")

    def test_returns_empty_dict_for_empty_html(self):
        self.assertEqual(extract_build_info(""), {})

    def test_handles_partial_info(self):
        html = '"SNlM0e":"xsrf-only"'
        info = extract_build_info(html)
        self.assertEqual(info["xsrf_token"], "xsrf-only")
        self.assertNotIn("build_label", info)


class TestSelectCookieString(unittest.TestCase):
    def test_selects_and_orders_cookies(self):
        cookies = [
            {"name": "SAPISID", "value": "val1", "domain": ".google.com"},
            {"name": "SID", "value": "val2", "domain": ".google.com"},
            {"name": "NID", "value": "ignored", "domain": ".google.com"},
        ]
        cookie, names = select_cookie_string(cookies)
        self.assertEqual(names, {"SAPISID", "SID"})
        # SID comes before SAPISID in PREFERRED_COOKIE_ORDER
        self.assertTrue(cookie.index("SID") < cookie.index("SAPISID"))

    def test_orders_by_preferred_order(self):
        cookies = [
            {"name": "__Secure-1PSID", "value": "a", "domain": ".google.com"},
            {"name": "SID", "value": "b", "domain": ".google.com"},
        ]
        cookie, names = select_cookie_string(cookies)
        self.assertEqual(names, {"__Secure-1PSID", "SID"})
        # SID (index 0) before __Secure-1PSID (index 5)
        self.assertTrue(cookie.index("SID") < cookie.index("__Secure-1PSID"))

    def test_empty_when_no_auth_cookies(self):
        cookies = [
            {"name": "NID", "value": "val", "domain": ".google.com"},
        ]
        cookie, names = select_cookie_string(cookies)
        self.assertEqual(names, set())
        self.assertEqual(cookie, "")

    def test_empty_value_cookies_skipped(self):
        cookies = [
            {"name": "SID", "value": "", "domain": ".google.com"},
            {"name": "SAPISID", "value": "valid", "domain": ".google.com"},
        ]
        cookie, names = select_cookie_string(cookies)
        self.assertEqual(names, {"SAPISID"})


class TestWriteSecretFile(unittest.TestCase):
    def test_writes_with_600_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret.txt"
            write_secret_file(path, "sensitive data\n")
            mode = path.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)
            self.assertEqual(path.read_text(), "sensitive data\n")


class TestWriteJsonFile(unittest.TestCase):
    def test_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            data = {"key": "value", "num": 42}
            write_json_file(path, data)
            self.assertEqual(json.loads(path.read_text()), data)


class TestReadJsonObject(unittest.TestCase):
    def test_reads_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"a": 1, "b": "hello"}')
            result = read_json_object(path)
            self.assertEqual(result, {"a": 1, "b": "hello"})

    def test_returns_empty_dict_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            self.assertEqual(read_json_object(path), {})

    def test_raises_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("not json")
            with self.assertRaises(RuntimeError):
                read_json_object(path)


class TestUpdateConfig(unittest.TestCase):
    def test_merges_patch_into_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            write_json_file(path, {"existing": "value"})
            update_config(path, {"new_key": "new_value"})
            result = read_json_object(path)
            self.assertEqual(result["existing"], "value")
            self.assertEqual(result["new_key"], "new_value")


class TestBuildLaunchArgs(unittest.TestCase):
    def test_builds_minimal_args(self):
        args = build_launch_args("/tmp/profile", None)
        self.assertEqual(args["user_data_dir"], "/tmp/profile")
        self.assertFalse(args["headless"])
        self.assertIn("--start-maximized", args["args"])

    def test_adds_profile_directory(self):
        args = build_launch_args("/tmp/profile", None, profile_directory="Profile 1")
        self.assertIn("--profile-directory=Profile 1", args["args"])

    def test_adds_browser_path(self):
        args = build_launch_args("/tmp/profile", "/usr/bin/chromium")
        self.assertEqual(args["executable_path"], "/usr/bin/chromium")


class TestAddCommonExportArgs(unittest.TestCase):
    def test_adds_all_expected_arguments(self):
        import argparse
        parser = argparse.ArgumentParser()
        add_common_export_args(parser)
        args = parser.parse_args([])
        self.assertTrue(hasattr(args, "profile_dir"))
        self.assertTrue(hasattr(args, "output_dir"))
        self.assertTrue(hasattr(args, "cookie_name"))
        self.assertTrue(hasattr(args, "self_test"))


class TestFindBrowser(unittest.TestCase):
    @patch("gemini_export._common.sync_playwright", None)
    def test_returns_explicit_path(self):
        self.assertEqual(find_browser("/usr/bin/chromium"), "/usr/bin/chromium")

    @patch("gemini_export._common.sync_playwright", None)
    @patch("shutil.which", return_value=None)
    def test_returns_none_when_nothing_found(self, mock_which):
        self.assertIsNone(find_browser(None))


if __name__ == "__main__":
    unittest.main()
