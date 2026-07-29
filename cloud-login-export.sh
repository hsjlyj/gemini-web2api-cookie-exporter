#!/usr/bin/env bash
set -Eeuo pipefail

# Cloud login launcher for export_gemini_cookie.py.
# Keep VNC/noVNC on loopback and access it only through an SSH tunnel.

BASE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DISPLAY_NUM="${DISPLAY_NUM:-99}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
SCREEN_SIZE="${SCREEN_SIZE:-1280x900x24}"
NOVNC_WEB="${NOVNC_WEB:-/usr/share/novnc}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf '缺少命令：%s\n' "$1" >&2
    printf 'Debian/Ubuntu 安装：apt-get update && apt-get install -y xvfb x11vnc novnc websockify\n' >&2
    exit 1
  }
}

for cmd in Xvfb x11vnc websockify; do
  need "$cmd"
done
need "$PYTHON_BIN"

if [[ ! -d "$NOVNC_WEB" ]]; then
  printf '找不到 noVNC 静态目录：%s\n' "$NOVNC_WEB" >&2
  printf '可用 --env NOVNC_WEB=/path/to/novnc 指定。\n' >&2
  exit 1
fi

if [[ -n "${DISPLAY:-}" ]]; then
  printf '警告：当前 DISPLAY=%s，将使用虚拟显示 :%s。\n' "$DISPLAY" "$DISPLAY_NUM" >&2
fi

XVFB_PID=""
VNC_PID=""
NOVNC_PID=""
cleanup() {
  set +e
  [[ -n "$NOVNC_PID" ]] && kill "$NOVNC_PID" 2>/dev/null || true
  [[ -n "$VNC_PID" ]] && kill "$VNC_PID" 2>/dev/null || true
  [[ -n "$XVFB_PID" ]] && kill "$XVFB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

Xvfb ":$DISPLAY_NUM" -screen 0 "$SCREEN_SIZE" -nolisten tcp >/tmp/gemini-export-xvfb.log 2>&1 &
XVFB_PID=$!
sleep 1
kill -0 "$XVFB_PID" 2>/dev/null || {
  cat /tmp/gemini-export-xvfb.log >&2 || true
  exit 1
}

# Both services bind to loopback. Do not expose VNC/noVNC directly to the Internet.
x11vnc -display ":$DISPLAY_NUM" -localhost -forever -shared -nopw -rfbport "$VNC_PORT" >/tmp/gemini-export-x11vnc.log 2>&1 &
VNC_PID=$!
sleep 1
kill -0 "$VNC_PID" 2>/dev/null || {
  cat /tmp/gemini-export-x11vnc.log >&2 || true
  exit 1
}

websockify --web="$NOVNC_WEB" --heartbeat 30 "127.0.0.1:$NOVNC_PORT" "127.0.0.1:$VNC_PORT" >/tmp/gemini-export-novnc.log 2>&1 &
NOVNC_PID=$!
sleep 1
kill -0 "$NOVNC_PID" 2>/dev/null || {
  cat /tmp/gemini-export-novnc.log >&2 || true
  exit 1
}

export DISPLAY=":$DISPLAY_NUM"
printf '\n远程浏览器已准备。\n'
printf '先在本地执行 SSH 隧道：ssh -N -L %s:127.0.0.1:%s root@服务器\n' "$NOVNC_PORT" "$NOVNC_PORT"
printf '然后打开：http://127.0.0.1:%s/vnc.html\n' "$NOVNC_PORT"
printf '在 noVNC 中完成 Google/Gemini 登录；脚本会自动继续导出。\n\n'

exec "$PYTHON_BIN" "$BASE_DIR/export_gemini_cookie.py" "$@"
