# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Exports Gemini Web cookies and tokens for the [`gemini-web2api`](https://github.com/Sophomoresty/gemini-web2api) API project. Automates Chromium-based Google/Gemini login via Playwright, extracts auth cookies plus XSRF and `gemini_bl` tokens, and writes them to the target API directory.

Cloud servers run headless via Xvfb + x11vnc + noVNC (loopback only, accessed through SSH tunnel).

## Architecture

Core logic lives in `gemini_export/_common.py` — a shared library that both entry points import:

- **Cookie selection** (`select_cookie_string`): filters Playwright cookies by `AUTH_COOKIE_NAMES`, orders by `PREFERRED_COOKIE_ORDER`, returns `name=value; ...` string.
- **Token extraction** (`extract_xsrf_token`, `extract_gemini_bl`): regex-based parsing of Gemini page HTML for `SNlM0e` and `boq_assistant-bard-web-server_*` values.
- **File I/O** (`write_secret_file`, `write_json_file`, `read_json_object`, `update_config`): writes with `0o600` permissions on Linux, merges config patches.
- **Browser discovery** (`find_browser`): tries Playwright bundled browser, ms-playwright cache, then system `google-chrome`/`chromium`/`msedge`.
- **Playwright import**: gracefully degrades — `sync_playwright = None` and `PlaywrightError = RuntimeError` when Playwright isn't installed.

Two entry points:

| Script | Purpose | Key Behavior |
|---|---|---|
| `export_gemini_cookie.py` | Interactive one-shot export | Opens browser, waits for user to complete Google login, extracts credentials |
| `gemini_cookie_watchdog.py` | Periodic refresh daemon (systemd timer) | Reuses existing authenticated Chrome profile; raises `AuthExpired` if session is lost |

Deployment scripts:

- `cloud-login-export.sh` — launches Xvfb/x11vnc/noVNC, then execs the Python exporter
- `repair-gemini-web2api-cloud.sh` — auto-detects mode (docker/direct), installs deps, creates venv, configures systemd services and watchdog timer
- `gemini-cookie-watchdog-runner.sh` — systemd unit runner wrapper

## Commands

```bash
# Run all tests (self-test + unit tests)
make test

# Self-test only (no browser, no side effects)
make self-test
# or individually:
python3 export_gemini_cookie.py --self-test
python3 gemini_cookie_watchdog.py --self-test

# Unit tests
make unit-test
# or individually:
python3 -m unittest tests.test_gemini_export -v
python3 -m unittest tests.test_browser_helpers -v

# Syntax check (py_compile)
make lint

# Format with black
make format

# Install Playwright for development
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install playwright
python3 -m playwright install chromium
```

## Key Invariants

- **File permissions**: `cookie.txt`, `gemini-export.json`, `config.json`, and `watchdog-state.json` must be `0o600` (set by `write_secret_file`).
- **Minimum required cookies**: `SID` and `SAPISID` must be present for a valid export.
- **Cookie string format**: `name=value; name=value` ordered by `PREFERRED_COOKIE_ORDER`.
- **XSRF token**: extracted from `SNlM0e` in Gemini page HTML; a page reload is tried if not found on first pass.
- **Watchdog exit codes**: `0` = healthy/refreshed, `2` = `auth_lost`, `3` = other error.
- **Never commit**: `cookie.txt`, `gemini-export.json`, `config.json`, browser profiles, or `watchdog-state.json`.

## Code Style

- Python 3.11+, 4-space indent, snake_case, `from __future__ import annotations` at top
- ruff config: line-length=100, select E/F/W/I, ignore E501
- Existing Chinese comments and error messages should be preserved
- Do not print cookie values or tokens in logs or exceptions

## Testing

Tests use `unittest` (not pytest despite the `pyproject.toml` pytest section). Tests in `tests/test_gemini_export.py` cover the pure-logic functions in `_common.py`. Tests in `tests/test_browser_helpers.py` cover `find_browser` and `wait_for_login` with mocked Playwright.

For detailed guidelines on project structure, commit conventions, and security, see `AGENTS.md`.
