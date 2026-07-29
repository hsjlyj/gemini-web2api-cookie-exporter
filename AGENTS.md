# Repository Guidelines

## Project Structure & Module Organization
- `export_gemini_cookie.py`: main export logic for Gemini cookies.
- `gemini_cookie_watchdog.py`: periodic login-session refresh logic.
- `cloud-login-export.sh`, `repair-gemini-web2api-cloud.sh`, `gemini-cookie-watchdog-runner.sh`: deployment helper scripts.
- `README.md`: usage, deployment, and troubleshooting instructions.
- Generated files such as `cookie.txt`, `gemini-export.json`, and `config.json` may appear in the target API directory at runtime.

## Build, Test, and Development Commands
- Create and use a virtual environment:
  - `python3 -m venv .venv && source .venv/bin/activate`
- Install runtime dependencies:
  - `python3 -m pip install --upgrade pip`
  - `python3 -m pip install playwright`
  - `python3 -m playwright install chromium`
- Self-check the exporter without browser automation side effects:
  - `python3 export_gemini_cookie.py --self-test`
- Run the helper scripts only in a safe test environment:
  - `bash cloud-login-export.sh --help`
  - `bash repair-gemini-web2api-cloud.sh --help`

## Coding Style & Naming Conventions
- Use Python 3 idioms with 4-space indentation.
- Prefer snake_case for Python files, functions, and variables.
- Use descriptive names for shell script options and environment variables.
- Keep functions small and focused; make side effects explicit.
- For shell scripts, use `set -euo pipefail` where practical.

## Testing Guidelines
- No full automated test suite is included in this repository.
- Before submitting, run affected scripts manually and confirm expected output paths and side effects.
- When adding new behavior, include a direct self-test path or a small reproducible command in the PR description.

## Commit & Pull Request Guidelines
- Write concise, imperative commit messages, for example: `export: add cookie validation` or `watchdog: handle auth_lost state`.
- A PR should include:
  - what changed and why,
  - manual verification steps or terminal output,
  - any affected files in the target API project,
  - linked issues or screenshots when login flows or browser behavior are involved.
- Keep changes focused; avoid unrelated refactors in the same PR.

## Security & Configuration Tips
- Do not commit `cookie.txt`, `gemini-export.json`, `config.json`, browser profiles, or secrets.
- Store runtime secrets in environment variables or protected config files, not in source code.
- When testing cloud login flows, use isolated Chrome profiles and avoid exposing VNC/noVNC ports publicly.

@RTK.md
