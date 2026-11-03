#!/usr/bin/env python3
"""Periodic Gemini credential refresh for gemini-web2api.

This refreshes cookies/tokens from an already authenticated cloud Chrome
profile. It does not automate Google password, MFA, CAPTCHA, or re-login.
Run it once per systemd timer tick under Xvfb.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from gemini_export._common import (
    GEMINI_URL,
    PlaywrightError,
    add_common_export_args,
    build_launch_args,
    extract_auth_user,
    extract_gemini_bl,
    extract_xsrf_token,
    find_browser,
    read_json_object,
    select_cookie_string,
    sync_playwright,
    update_config,
    write_json_file,
    write_secret_file,
)


class AuthExpired(RuntimeError):
    """The persistent Chrome profile is no longer authenticated to Gemini."""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())



def collect_from_profile(args: argparse.Namespace) -> dict[str, Any]:
    if sync_playwright is None:
        raise RuntimeError(
            "缺少 Playwright。请安装 playwright，并执行 playwright install chromium。"
        )

    profile_dir = Path(args.profile_dir).expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    browser_path = find_browser(args.browser)
    launch_args = build_launch_args(profile_dir, browser_path, args.profile_directory)

    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(**launch_args)
        except PlaywrightError as exc:
            raise RuntimeError(
                "无法打开 Chrome Profile。请确认没有其他 Chrome 进程占用该 Profile。"
            ) from exc

        try:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=args.navigation_timeout)
            except PlaywrightError:
                # A redirect or a navigation timeout can still leave a usable
                # authenticated page; inspect URL/cookies below.
                pass
            page.wait_for_timeout(args.settle_seconds * 1000)

            cookies = context.cookies([GEMINI_URL])
            cookie_string, cookie_names = select_cookie_string(cookies)
            url = page.url or ""
            if "gemini.google.com" not in url or "SAPISID" not in cookie_names:
                raise AuthExpired(
                    f"Gemini 登录态失效或被重定向，当前页面：{url[:180]}"
                )

            # 并行提取 HTML 中的 token 和构建信息
            html = page.content()
            xsrf_token = extract_xsrf_token(html)
            gemini_bl = extract_gemini_bl(html)
            if not xsrf_token:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=args.navigation_timeout)
                    page.wait_for_timeout(1500)
                    html = page.content()
                    xsrf_token = extract_xsrf_token(html)
                    gemini_bl = gemini_bl or extract_gemini_bl(html)
                except PlaywrightError:
                    pass

            logger.info(
                "Cookie 刷新成功: %s, xsrf_token=%s, gemini_bl=%s",
                ", ".join(cookie_names),
                xsrf_token[:8] + "..." if xsrf_token else None,
                gemini_bl,
            )
            return {
                "cookie_string": cookie_string,
                "cookie_names": sorted(cookie_names),
                "xsrf_token": xsrf_token,
                "gemini_bl": gemini_bl,
                "auth_user": extract_auth_user(url),
                "url": url,
            }
        finally:
            context.close()


def apply_outputs(args: argparse.Namespace, result: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie_path = output_dir / args.cookie_name
    cookie_value = result["cookie_string"] + "\n"
    old_cookie = cookie_path.read_text(encoding="utf-8") if cookie_path.exists() else None
    cookie_changed = old_cookie != cookie_value
    if cookie_changed:
        write_secret_file(cookie_path, cookie_value)

    config_path = Path(args.config).expanduser().resolve() if args.config else output_dir / "config.json"
    config_cookie_file = args.config_cookie_file or str(cookie_path)
    patch: dict[str, Any] = {
        "cookie_file": config_cookie_file,
        "auth_user": result["auth_user"],
    }
    if result["xsrf_token"]:
        patch["xsrf_token"] = result["xsrf_token"]
    if result["gemini_bl"]:
        patch["gemini_bl"] = result["gemini_bl"]

    if config_path.exists() or args.write_config:
        old_config = read_json_object(config_path)
        config_changed = any(old_config.get(key) != value for key, value in patch.items())
        if config_changed:
            update_config(config_path, patch)
        config_output = config_path
    else:
        config_output = output_dir / "gemini-export.json"
        old_config = read_json_object(config_output)
        config_changed = any(old_config.get(key) != value for key, value in patch.items())
        if config_changed:
            write_json_file(config_output, patch)

    restart_performed = False
    if config_changed and args.restart_command:
        command = shlex.split(args.restart_command)
        if not command:
            raise RuntimeError("restart-command 为空")
        subprocess.run(command, check=True, timeout=args.restart_timeout)
        restart_performed = True

    status = "refreshed" if cookie_changed or config_changed else "healthy"
    state = {
        "checked_at": now_iso(),
        "status": status,
        "cookie_changed": cookie_changed,
        "config_changed": config_changed,
        "restart_performed": restart_performed,
        "cookie_names": result["cookie_names"],
        "page_url": result["url"],
        "cookie_file": str(cookie_path),
        "config_file": str(config_output),
    }
    state_path = Path(args.state_file).expanduser().resolve()
    write_json_file(state_path, state)
    return state


def write_failure_state(args: argparse.Namespace, status: str, error: str) -> None:
    state_path = Path(args.state_file).expanduser().resolve()
    write_json_file(
        state_path,
        {
            "checked_at": now_iso(),
            "status": status,
            "error": error[:500],
        },
    )


def self_test() -> int:
    html = '"SNlM0e":"xsrf-demo","build":"boq_assistant-bard-web-server_20260714.01_p0"'
    assert extract_xsrf_token(html) == "xsrf-demo"
    assert extract_gemini_bl(html) == "boq_assistant-bard-web-server_20260714.01_p0"
    print("watchdog self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="定时刷新 gemini-web2api 的 Gemini Cookie/XSRF 配置")
    add_common_export_args(parser)
    parser.add_argument("--write-config", action="store_true")
    parser.add_argument("--state-file", default="/var/lib/gemini-web2api/watchdog-state.json")
    parser.add_argument("--restart-command", help="xsrf_token/gemini_bl 变化后执行的单条重启命令")
    parser.add_argument("--restart-timeout", type=int, default=120)
    parser.add_argument("--navigation-timeout", type=int, default=60_000)
    parser.add_argument("--settle-seconds", type=int, default=3)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        return self_test()
    try:
        state = apply_outputs(args, collect_from_profile(args))
        print(json.dumps(state, ensure_ascii=False, separators=(",", ":")))
        return 0
    except AuthExpired as exc:
        write_failure_state(args, "auth_lost", str(exc))
        print(f"AUTH_LOST: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        write_failure_state(args, "error", str(exc))
        print(f"WATCHDOG_ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
