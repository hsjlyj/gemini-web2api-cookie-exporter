from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from gemini_export._common import (
    AUTH_COOKIE_NAMES,
    GEMINI_URL,
    MINIMUM_COOKIE_NAMES,
    PREFERRED_COOKIE_ORDER,
    PlaywrightError,
    add_common_export_args,
    build_launch_args,
    extract_auth_user,
    extract_gemini_bl,
    extract_xsrf_token,
    find_browser,
    select_cookie_string,
    sync_playwright,
    update_config,
    write_json_file,
    write_secret_file,
)


def wait_for_login(context: Any, page: Any, timeout: int) -> None:
    """Wait until a Gemini-domain login cookie appears."""
    deadline = time.monotonic() + timeout
    last_notice = 0.0
    while time.monotonic() < deadline:
        cookies = context.cookies([GEMINI_URL])
        names = {item.get("name") for item in cookies}
        url = page.url or ""
        if "SAPISID" in names and "gemini.google.com" in url:
            page.wait_for_timeout(2500)
            return

        now = time.monotonic()
        if now - last_notice >= 10:
            print("等待 Gemini 登录完成；请在打开的浏览器窗口中登录 Google。")
            last_notice = now
        page.wait_for_timeout(1000)
    raise TimeoutError("在限定时间内没有检测到 Gemini 登录 Cookie。")


def collect_credentials(
    profile_dir: Path,
    browser_path: str | None,
    timeout: int,
    profile_directory: str | None = None,
) -> dict[str, Any]:
    if sync_playwright is None:
        raise RuntimeError(
            "缺少 Playwright。请先执行：python3 -m pip install playwright && "
            "python3 -m playwright install chromium"
        )

    profile_dir.mkdir(parents=True, exist_ok=True)
    launch_args = build_launch_args(profile_dir, browser_path, profile_directory)

    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(**launch_args)
        except PlaywrightError as exc:
            raise RuntimeError(
                "无法启动 Chrome/Chromium。可以用 --browser 指定浏览器路径，或安装 Playwright 浏览器。"
            ) from exc

        try:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60_000)
            except PlaywrightError as exc:
                print(f"首次打开 Gemini 页面出现提示：{exc}", file=sys.stderr)

            print(f"浏览器已打开：{GEMINI_URL}")
            print("首次运行请在该窗口完成 Google 登录；登录成功后脚本会自动导出。")
            wait_for_login(context, page, timeout)

            # Login can leave the browser on an account-selection page. Return
            # to Gemini so the rendered HTML contains SNlM0e and build data.
            if "gemini.google.com" not in (page.url or ""):
                page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2500)
            html = page.content()
            xsrf_token = extract_xsrf_token(html)
            gemini_bl = extract_gemini_bl(html)

            # A reload often makes the rendered bootstrap token appear after
            # the first authenticated navigation.
            if not xsrf_token:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(2000)
                    html = page.content()
                    xsrf_token = extract_xsrf_token(html)
                    gemini_bl = gemini_bl or extract_gemini_bl(html)
                except PlaywrightError:
                    pass

            cookies = context.cookies([GEMINI_URL])
            cookie_string, found_names = select_cookie_string(cookies)
            if not cookie_string:
                raise RuntimeError("已打开 Gemini，但没有读取到可用的认证 Cookie。")

            return {
                "cookie_string": cookie_string,
                "cookie_names": sorted(found_names),
                "xsrf_token": xsrf_token,
                "gemini_bl": gemini_bl,
                "auth_user": extract_auth_user(page.url or ""),
                "source_url": page.url,
            }
        finally:
            context.close()


def run_export(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie_path = output_dir / args.cookie_name
    profile_dir = Path(args.profile_dir).expanduser().resolve()
    browser_path = find_browser(args.browser)

    if browser_path:
        print(f"使用浏览器：{browser_path}")
    else:
        print("未找到系统 Chrome/Chromium，将尝试 Playwright 自带浏览器。")

    result = collect_credentials(
        profile_dir,
        browser_path,
        args.timeout,
        args.profile_directory,
    )
    write_secret_file(cookie_path, result["cookie_string"] + "\n")

    # This patch contains the XSRF token and therefore receives restrictive
    # permissions too. It does not duplicate the raw cookie value.
    config_cookie_file = args.config_cookie_file or str(cookie_path)
    config_patch: dict[str, Any] = {
        "cookie_file": config_cookie_file,
        "auth_user": result["auth_user"],
    }
    if result["xsrf_token"]:
        config_patch["xsrf_token"] = result["xsrf_token"]
    if result["gemini_bl"]:
        config_patch["gemini_bl"] = result["gemini_bl"]

    config_path = Path(args.config).expanduser().resolve() if args.config else output_dir / "config.json"
    if config_path.exists() or args.write_config:
        update_config(config_path, config_patch)
        config_message = f"已更新配置：{config_path}"
    else:
        export_path = output_dir / "gemini-export.json"
        write_json_file(export_path, config_patch)
        config_message = f"未发现 config.json；已写出配置补丁：{export_path}"

    missing = sorted(MINIMUM_COOKIE_NAMES - set(result["cookie_names"]))
    print(f"已导出 Cookie：{cookie_path}")
    print(config_message)
    print(f"已捕获 Cookie 项：{len(result['cookie_names'])} 个（名称：{', '.join(result['cookie_names'])}）")
    if missing:
        print(f"警告：缺少关键 Cookie：{', '.join(missing)}", file=sys.stderr)
    if not result["xsrf_token"]:
        print("警告：未自动捕获 xsrf_token；如请求返回 xsrf 错误，请刷新 Gemini 页面后重跑。", file=sys.stderr)
    if not result["gemini_bl"]:
        print("提示：未捕获 gemini_bl，现有配置值会保持不变。", file=sys.stderr)
    print("安全提示：cookie.txt 与配置补丁包含登录凭证，请勿提交 Git 或发送给他人。")
    return 0


def self_test() -> int:
    html = '"SNlM0e":"xsrf-demo","build":"boq_assistant-bard-web-server_20260714.01_p0"'
    assert extract_xsrf_token(html) == "xsrf-demo"
    assert extract_gemini_bl(html) == "boq_assistant-bard-web-server_20260714.01_p0"
    assert extract_auth_user("https://gemini.google.com/u/1/app/abc") == "1"
    assert extract_auth_user("https://gemini.google.com/app") is None

    # 测试 extract_build_info
    info = extract_build_info(html)
    assert info["xsrf_token"] == "xsrf-demo"
    assert info["build_label"] == "boq_assistant-bard-web-server_20260714.01_p0"
    assert extract_build_info("") == {}

    cookie, names = select_cookie_string(
        [
            {"name": "SAPISID", "value": "secret-sapisid", "domain": ".google.com"},
            {"name": "SID", "value": "secret-sid", "domain": ".google.com"},
            {"name": "irrelevant", "value": "ignored", "domain": ".google.com"},
        ]
    )
    assert cookie.startswith("SID=secret-sid; SAPISID=secret-sapisid")
    assert names == {"SID", "SAPISID"}

    # 测试 __Secure- 系列 Cookie 排序
    cookie2, names2 = select_cookie_string(
        [
            {"name": "__Secure-1PSID", "value": "secure-val", "domain": ".google.com"},
            {"name": "SID", "value": "sid-val", "domain": ".google.com"},
        ]
    )
    assert names2 == {"__Secure-1PSID", "SID"}
    assert cookie2.index("SID") < cookie2.index("__Secure-1PSID")

    print("self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="一键导出 gemini-web2api 所需的 Gemini Cookie/XSRF 配置")
    add_common_export_args(parser)
    parser.add_argument("--write-config", action="store_true", help="config.json 不存在时也创建它")
    parser.add_argument("--timeout", type=int, default=600, help="等待登录秒数，默认 600")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        return self_test()
    try:
        return run_export(args)
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
