from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gemini_cookie_watchdog import (
    AuthExpired,
    apply_outputs,
    now_iso,
    self_test,
    write_failure_state,
)


class TestWatchdogSelfTest(unittest.TestCase):
    def test_self_test_passes(self):
        self.assertEqual(self_test(), 0)


class TestWatchdogNowIso(unittest.TestCase):
    def test_now_iso_format(self):
        import re
        self.assertRegex(now_iso(), r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class TestWriteFailureState(unittest.TestCase):
    def test_writes_error_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            write_failure_state(
                type("Args", (), {"state_file": str(state_path)})(),
                "auth_lost",
                "Session expired",
            )
            data = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "auth_lost")
            self.assertEqual(data["error"], "Session expired")
            self.assertIn("checked_at", data)

    def test_truncates_long_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            long_error = "x" * 600
            write_failure_state(
                type("Args", (), {"state_file": str(state_path)})(),
                "error",
                long_error,
            )
            data = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["error"]), 500)


class TestApplyOutputs(unittest.TestCase):
    def _make_args(self, **overrides):
        defaults = {
            "output_dir": ".",
            "cookie_name": "cookie.txt",
            "config": None,
            "config_cookie_file": None,
            "write_config": False,
            "state_file": str(Path(tempfile.gettempdir()) / "watchdog-test-state.json"),
            "restart_command": None,
            "restart_timeout": 120,
        }
        defaults.update(overrides)
        return type("Args", (), defaults)()

    def test_no_changes_when_identical(self):
        from gemini_export._common import write_json_file

        with tempfile.TemporaryDirectory() as tmp:
            args = self._make_args(output_dir=tmp)
            cookie_path = Path(tmp) / "cookie.txt"
            # apply_outputs appends "\n" to result["cookie_string"] before writing,
            # so the existing file must also have the trailing newline to match.
            cookie_path.write_text("SID=s1; SAPISID=s2\n", encoding="utf-8")

            # Pre-create gemini-export.json with matching values so config_changed=False
            export_path = Path(tmp) / "gemini-export.json"
            write_json_file(export_path, {"cookie_file": str(cookie_path), "auth_user": "0"})

            result = {
                "cookie_string": "SID=s1; SAPISID=s2",
                "cookie_names": ["SAPISID", "SID"],
                "xsrf_token": None,
                "gemini_bl": None,
                "auth_user": "0",
                "url": "https://gemini.google.com/app",
            }
            state = apply_outputs(args, result)
            self.assertEqual(state["status"], "healthy")
            self.assertFalse(state["cookie_changed"])
            self.assertFalse(state["config_changed"])

    def test_cookie_changed_writes_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._make_args(output_dir=tmp)
            cookie_path = Path(tmp) / "cookie.txt"
            cookie_path.write_text("old-value\n", encoding="utf-8")

            result = {
                "cookie_string": "SID=new-sid; SAPISID=new-sapi",
                "cookie_names": ["SAPISID", "SID"],
                "xsrf_token": "new-xsrf",
                "gemini_bl": None,
                "auth_user": "0",
                "url": "https://gemini.google.com/app",
            }
            state = apply_outputs(args, result)
            self.assertEqual(state["status"], "refreshed")
            self.assertTrue(state["cookie_changed"])
            self.assertTrue(state["config_changed"])
            self.assertEqual(
                cookie_path.read_text(encoding="utf-8"),
                "SID=new-sid; SAPISID=new-sapi\n",
            )

    def test_writes_gemini_export_json_when_no_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._make_args(output_dir=tmp)
            result = {
                "cookie_string": "SID=s1; SAPISID=s2",
                "cookie_names": ["SAPISID", "SID"],
                "xsrf_token": "xsrf-val",
                "gemini_bl": "boq_assistant-bard-web-server_20260101.01_p0",
                "auth_user": "0",
                "url": "https://gemini.google.com/app",
            }
            state = apply_outputs(args, result)
            export_path = Path(tmp) / "gemini-export.json"
            self.assertTrue(export_path.exists())
            data = json.loads(export_path.read_text(encoding="utf-8"))
            self.assertEqual(data["xsrf_token"], "xsrf-val")
            self.assertEqual(data["gemini_bl"], "boq_assistant-bard-web-server_20260101.01_p0")
            self.assertEqual(data["auth_user"], "0")

    def test_restart_command_invokes_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._make_args(
                output_dir=tmp,
                restart_command="echo restarted",
                write_config=True,
            )
            result = {
                "cookie_string": "SID=s1; SAPISID=s2",
                "cookie_names": ["SAPISID", "SID"],
                "xsrf_token": "new-xsrf",
                "gemini_bl": None,
                "auth_user": "0",
                "url": "https://gemini.google.com/app",
            }
            with patch("subprocess.run") as mock_run:
                state = apply_outputs(args, result)
                mock_run.assert_called_once_with(
                    ["echo", "restarted"],
                    check=True,
                    timeout=120,
                )
            self.assertTrue(state["restart_performed"])

    def test_config_file_permissions_are_600(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._make_args(output_dir=tmp)
            result = {
                "cookie_string": "SID=s1; SAPISID=s2",
                "cookie_names": ["SAPISID", "SID"],
                "xsrf_token": None,
                "gemini_bl": None,
                "auth_user": "0",
                "url": "https://gemini.google.com/app",
            }
            apply_outputs(args, result)
            for f in Path(tmp).iterdir():
                if f.is_file():
                    mode = f.stat().st_mode & 0o777
                    self.assertEqual(mode, 0o600, msg=f"{f.name} has mode {oct(mode)}")


class TestCollectFromProfile(unittest.TestCase):
    def test_missing_playwright_raises(self):
        args = type("Args", (), {
            "profile_dir": "/tmp/no-such-dir",
            "browser": None,
            "profile_directory": None,
            "navigation_timeout": 1000,
            "settle_seconds": 1,
        })()
        with patch("gemini_cookie_watchdog.sync_playwright", None):
            with self.assertRaises(RuntimeError):
                from gemini_cookie_watchdog import collect_from_profile
                collect_from_profile(args)

    def test_auth_expired_raised_when_no_sapisid(self):
        from gemini_cookie_watchdog import collect_from_profile

        mock_context = MagicMock()
        mock_context.cookies.return_value = [
            {"name": "SID", "value": "sid", "domain": ".google.com"},
        ]
        mock_page = MagicMock()
        mock_page.url = "https://accounts.google.com"
        mock_page.content.return_value = ""
        mock_page.wait_for_timeout = MagicMock()

        mock_playwright = MagicMock()
        mock_playwright.chromium.launch_persistent_context.return_value = mock_context
        mock_context.pages = [mock_page]

        args = type("Args", (), {
            "profile_dir": "/tmp/no-such-dir",
            "browser": None,
            "profile_directory": None,
            "navigation_timeout": 1000,
            "settle_seconds": 1,
        })()

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mock_playwright)
        cm.__exit__ = MagicMock(return_value=False)
        with patch("gemini_cookie_watchdog.sync_playwright", return_value=cm):
            with self.assertRaises(AuthExpired):
                collect_from_profile(args)


if __name__ == "__main__":
    unittest.main()
