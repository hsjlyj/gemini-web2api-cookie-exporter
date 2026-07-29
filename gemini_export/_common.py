from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    PlaywrightError = RuntimeError  # type: ignore[assignment]
    sync_playwright = None  # type: ignore[assignment]


GEMINI_URL = "https://gemini.google.com/app"

AUTH_COOKIE_NAMES = {
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "__Secure-1PSID",
    "__Secure-1PSIDTS",
    "__Secure-1PAPISID",
    "__Secure-3PSID",
    "__Secure-3PSIDTS",
    "__Secure-3PAPISID",
    "OSID",
    "__Secure-OSID",
    "LSID",
}

MINIMUM_COOKIE_NAMES = {"SID", "SAPISID"}
PREFERRED_COOKIE_ORDER = [
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "__Secure-1PSID",
    "__Secure-1PSIDTS",
    "__Secure-1PAPISID",
    "__Secure-3PSID",
    "__Secure-3PSIDTS",
    "__Secure-3PAPISID",
    "OSID",
    "__Secure-OSID",
    "LSID",
]


def extract_xsrf_token(html: str) -> str | None:
    patterns = (
        r'"SNlM0e"\s*:\s*"([^"\\]+)"',
        r'"SNlM0e"\s*,\s*"([^"\\]+)"',
        r"SNlM0e\\?['\"]\s*[,=:]\s*\\?['\"]([^'\"\\]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return None


def extract_gemini_bl(html: str) -> str | None:
    matches = re.findall(r"boq_assistant-bard-web-server_[A-Za-z0-9._-]+", html)
    if not matches:
        return None
    return max(matches, key=len)


def extract_auth_user(url: str) -> str | None:
    match = re.search(r"gemini\.google\.com/u/(\d+)(?:/|$)", url)
    return match.group(1) if match else None


def select_cookie_string(cookies: list[dict[str, Any]]) -> tuple[str, set[str]]:
    selected = {
        item["name"]: str(item.get("value", ""))
        for item in cookies
        if item.get("name") in AUTH_COOKIE_NAMES and item.get("value")
    }
    ordered_names = [name for name in AUTH_COOKIE_NAMES if name in selected]
    order = {name: index for index, name in enumerate(PREFERRED_COOKIE_ORDER)}
    ordered_names.sort(key=lambda name: (order.get(name, len(order)), name))
    cookie_string = "; ".join(f"{name}={selected[name]}" for name in ordered_names)
    return cookie_string, set(selected)


def write_secret_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    write_secret_file(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"配置文件不是有效 JSON：{path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"配置文件顶层必须是 JSON 对象：{path}")
    return value


def update_config(config_path: Path, patch: dict[str, Any]) -> None:
    config = read_json_object(config_path)
    config.update(patch)
    write_json_file(config_path, config)


def find_browser(explicit: str | None) -> str | None:
    if explicit:
        return explicit

    if sync_playwright is not None:
        try:
            with sync_playwright() as playwright:
                bundled = Path(playwright.chromium.executable_path)
            if bundled.exists():
                return str(bundled)

            cache_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
            cache_root = Path(cache_env).expanduser() if cache_env else Path.home() / ".cache" / "ms-playwright"
            candidates = list(cache_root.glob("chromium-*/chrome-linux64/chrome"))
            candidates += list(cache_root.glob("chromium-*/chrome-win/chrome.exe"))
            candidates += list(cache_root.glob("chromium-*/chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"))
            existing = [candidate for candidate in candidates if candidate.exists()]
            if existing:
                return str(sorted(existing, key=lambda p: str(p))[-1])
        except Exception:
            pass

    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "msedge",
    ):
        found = shutil.which(name)
        if found:
            return found
    return None


def build_launch_args(
    profile_dir: str | Path,
    browser_path: str | None,
    profile_directory: str | None = None,
) -> dict[str, Any]:
    """Build the keyword-argument dict for ``launch_persistent_context``."""
    launch_args: dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": False,
        "args": ["--start-maximized"],
    }
    if profile_directory:
        launch_args["args"].append(f"--profile-directory={profile_directory}")
    if browser_path:
        launch_args["executable_path"] = browser_path
    return launch_args


def add_common_export_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile-dir",
        default="~/.gemini-web2api-exporter/chrome-profile",
        help="专用 Chrome 配置目录；首次登录后会复用，默认 ~/.gemini-web2api-exporter/chrome-profile",
    )
    parser.add_argument(
        "--profile-directory",
        help="已有 Chrome user-data-dir 内的账号目录，例如 Default 或 Profile 1",
    )
    parser.add_argument("--browser", help="Chrome/Chromium 可执行文件路径")
    parser.add_argument("--output-dir", default=".", help="输出目录，默认当前目录")
    parser.add_argument("--cookie-name", default="cookie.txt", help="Cookie 文件名，默认 cookie.txt")
    parser.add_argument("--config", help="要更新的 config.json 路径")
    parser.add_argument(
        "--config-cookie-file",
        help="写入 config.json 的 cookie_file 值；Docker 中可设为 /app/cookie.txt",
    )
    parser.add_argument("--self-test", action="store_true", help="只运行本地解析测试，不启动浏览器")
