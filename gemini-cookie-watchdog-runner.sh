#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/gemini-web2api-cookie-exporter}"
PYTHON_BIN="${PYTHON_BIN:-/opt/gemini-export-venv/bin/python}"
PROFILE_DIR="${PROFILE_DIR:-/root/.gemini-web2api-exporter/chrome-profile}"
PROFILE_DIRECTORY="${PROFILE_DIRECTORY:-}"
OUTPUT_DIR="${OUTPUT_DIR:-/opt/gemini-web2api}"
CONFIG_PATH="${CONFIG_PATH:-}"
CONFIG_COOKIE_FILE="${CONFIG_COOKIE_FILE:-/app/cookie.txt}"
STATE_FILE="${STATE_FILE:-/var/lib/gemini-web2api/watchdog-state.json}"
RESTART_COMMAND="${RESTART_COMMAND:-}"

args=(
  "$APP_DIR/gemini_cookie_watchdog.py"
  --profile-dir "$PROFILE_DIR"
  --output-dir "$OUTPUT_DIR"
  --config-cookie-file "$CONFIG_COOKIE_FILE"
  --state-file "$STATE_FILE"
)
[[ -n "$PROFILE_DIRECTORY" ]] && args+=(--profile-directory "$PROFILE_DIRECTORY")
[[ -n "$CONFIG_PATH" ]] && args+=(--config "$CONFIG_PATH")
[[ -n "$RESTART_COMMAND" ]] && args+=(--restart-command "$RESTART_COMMAND")

exec "$PYTHON_BIN" "${args[@]}"
