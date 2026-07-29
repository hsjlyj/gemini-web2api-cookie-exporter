from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from export_gemini_cookie import find_browser, wait_for_login
from gemini_export._common import GEMINI_URL


class TestBrowserHelpers(unittest.TestCase):
    def test_find_browser_returns_explicit_path(self):
        explicit = "/usr/bin/chromium"
        self.assertEqual(find_browser(explicit), explicit)

    def test_wait_for_login_notices_pending_auth_once_per_interval(self):
        context = MagicMock()
        page = MagicMock()
        context.cookies.side_effect = [
            [],
            [],
            [{"name": "SAPISID", "value": "token", "domain": ".google.com"}],
        ]
        page.url = "https://gemini.google.com/app"
        page.wait_for_timeout = MagicMock(side_effect=[1000, 1000, 2500])

        wait_for_login(context, page, timeout=30)

        self.assertEqual(context.cookies.call_count, 3)
        self.assertEqual(page.wait_for_timeout.call_args_list[0], ((1000,),))
        self.assertEqual(page.wait_for_timeout.call_args_list[-1], ((2500,),))

    def test_wait_for_login_returns_once_gemini_cookie_appears(self):
        context = MagicMock()
        page = MagicMock()
        cookies = [
            {"name": "SAPISID", "value": "secret-sapisid", "domain": ".google.com"},
        ]
        context.cookies.return_value = cookies
        page.url = "https://gemini.google.com/app"
        page.wait_for_timeout = MagicMock()

        wait_for_login(context, page, timeout=5)

        context.cookies.assert_called_once_with([GEMINI_URL])
        page.wait_for_timeout.assert_called_once_with(2500)

    def test_wait_for_login_raises_after_timeout(self):
        context = MagicMock()
        page = MagicMock()
        context.cookies.return_value = []
        page.url = "https://accounts.google.com"
        page.wait_for_timeout = MagicMock()

        with self.assertRaises(TimeoutError):
            wait_for_login(context, page, timeout=1)

        self.assertTrue(page.wait_for_timeout.called)


if __name__ == "__main__":
    unittest.main()
