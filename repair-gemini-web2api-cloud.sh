#!/usr/bin/env bash
set -Eeuo pipefail

# Self-healing preflight/deployer for gemini-web2api + exporter/watchdog.
# Default behavior repairs missing reversible dependencies and services.
# It never creates Google credentials or bypasses login/MFA/CAPTCHA.

BUNDLE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="/opt/gemini-web2api"
VENV_DIR="/opt/gemini-export-venv"
MODE="auto"
CHECK_ONLY=0
INSTALL_WATCHDOG=1
RUN_USER="root"

usage() {
  cat <<'EOF'
Usage: repair-gemini-web2api-cloud.sh [options]

Options:
  --mode auto|direct|docker   Deployment mode (default: auto)
  --api-dir PATH              Upstream repo/runtime directory
  --venv PATH                 Python venv for API/exporter
  --check-only                Detect and report; do not install or modify
  --no-watchdog               Do not install/repair the 4-hour timer
  --user USER                 Linux user for the direct systemd service
  -h, --help                  Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --api-dir) API_DIR="$2"; shift 2 ;;
    --venv) VENV_DIR="$2"; shift 2 ;;
    --check-only) CHECK_ONLY=1; shift ;;
    --no-watchdog) INSTALL_WATCHDOG=0; shift ;;
    --user) RUN_USER="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf '未知参数：%s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  printf 'repair 需要 root 权限。\n' >&2
  exit 1
fi

if [[ "$MODE" != auto && "$MODE" != direct && "$MODE" != docker ]]; then
  printf '无效 mode：%s\n' "$MODE" >&2
  exit 2
fi

log() { printf '[repair] %s\n' "$*"; }
fail() { printf '[repair][ERROR] %s\n' "$*" >&2; exit 1; }

if [[ "$MODE" == auto ]]; then
  if [[ -f "$API_DIR/docker-compose.local.yml" ]] || command -v docker >/dev/null 2>&1; then
    MODE="docker"
  else
    MODE="direct"
  fi
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
  log "check-only mode; no installation, file write, service restart, or compose action"
else
  export DEBIAN_FRONTEND=noninteractive
fi

apt_install() {
  [[ $CHECK_ONLY -eq 1 ]] && return 0
  apt-get update
  apt-get install -y --no-install-recommends "$@"
}

need_commands=(git python3 Xvfb x11vnc websockify)
if [[ "$MODE" == docker ]]; then
  need_commands+=(docker)
fi
missing=()
for cmd in "${need_commands[@]}"; do
  command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  log "缺少命令：${missing[*]}"
  [[ $CHECK_ONLY -eq 1 ]] && fail "check-only 检测到缺少依赖"
  apt_install git python3 python3-venv xvfb x11vnc novnc websockify
  if [[ "$MODE" == docker ]] && ! command -v docker >/dev/null 2>&1; then
    apt_install docker.io docker-compose-plugin || apt_install docker.io docker-compose
    systemctl enable --now docker 2>/dev/null || true
  fi
fi

if [[ "$MODE" == docker ]] && ! docker compose version >/dev/null 2>&1; then
  if [[ $CHECK_ONLY -eq 1 ]]; then
    fail "docker compose 插件不可用"
  fi
  apt_install docker-compose-plugin || fail "无法安装 docker-compose-plugin；请先修复 Docker Compose"
fi

if [[ ! -d "$API_DIR" ]]; then
  [[ $CHECK_ONLY -eq 1 ]] && fail "缺少 API 目录：$API_DIR"
  log "克隆 upstream：$API_DIR"
  git clone https://github.com/Sophomoresty/gemini-web2api.git "$API_DIR"
fi

for required in gemini_web2api Dockerfile requirements.txt config.example.json; do
  [[ -e "$API_DIR/$required" ]] || fail "API 项目缺少必要文件：$API_DIR/$required"
done

if [[ ! -d "$VENV_DIR" ]]; then
  [[ $CHECK_ONLY -eq 1 ]] && fail "缺少 Python venv：$VENV_DIR"
  log "创建 venv：$VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi
PYTHON_BIN="$VENV_DIR/bin/python"
[[ -x "$PYTHON_BIN" ]] || fail "venv Python 不可执行：$PYTHON_BIN"

if ! "$PYTHON_BIN" -c 'import sys; exit(0)' >/dev/null 2>&1; then
  fail "venv 无法执行：$PYTHON_BIN"
fi

if [[ $CHECK_ONLY -eq 0 ]]; then
  "$PYTHON_BIN" -m pip install -r "$API_DIR/requirements.txt"
  "$PYTHON_BIN" -m pip install playwright
  "$PYTHON_BIN" -m playwright install chromium
else
  "$PYTHON_BIN" -c 'import httpx' >/dev/null 2>&1 || fail "venv 缺少 httpx"
  "$PYTHON_BIN" -c 'import playwright' >/dev/null 2>&1 || fail "venv 缺少 playwright"
fi

CONFIG="$API_DIR/config.json"
if [[ ! -f "$CONFIG" ]]; then
  [[ $CHECK_ONLY -eq 1 ]] && fail "缺少 config.json：$CONFIG"
  cp "$API_DIR/config.example.json" "$CONFIG"
  chmod 600 "$CONFIG"
  log "已从 config.example.json 创建 config.json；API key/cookie 仍需真实配置"
fi

python3 - "$CONFIG" "$MODE" "$API_DIR" <<'PY'
import json, os, sys
from pathlib import Path
p = Path(sys.argv[1])
mode = sys.argv[2]
api_dir = Path(sys.argv[3])
data = json.loads(p.read_text(encoding='utf-8'))
if not isinstance(data, dict):
    raise SystemExit('config.json 顶层必须是对象')
changed = False
if not data.get('cookie_file'):
    data['cookie_file'] = '/app/cookie.txt' if mode == 'docker' else str(api_dir / 'cookie.txt')
    changed = True
if changed:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.chmod(p, 0o600)
PY

if [[ "$MODE" == docker ]]; then
  COMPOSE="$API_DIR/docker-compose.local.yml"
  [[ -f "$COMPOSE" ]] || fail "缺少 upstream Compose 文件：$COMPOSE"
  if [[ $CHECK_ONLY -eq 0 ]]; then
    python3 - "$COMPOSE" <<'PY'
import os, sys
from pathlib import Path
p = Path(sys.argv[1])
s = p.read_text(encoding='utf-8')
needle = './cookie.txt:/app/cookie.txt'
if needle not in s:
    marker = '      - ./config.json:/app/config.json\n'
    if marker not in s:
        raise SystemExit('无法安全修复 Compose：找不到 config.json volume 行')
    backup = p.with_name(p.name + '.bak')
    if not backup.exists():
        backup.write_text(s, encoding='utf-8')
    s = s.replace(marker, marker + '      - ./cookie.txt:/app/cookie.txt:ro\n', 1)
    p.write_text(s, encoding='utf-8')
PY
     # 检测 Docker Compose 版本 (v1 vs v2)
     if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
       DC="docker compose"
     elif command -v docker-compose >/dev/null 2>&1; then
       DC="docker-compose"
     else
       fail "未找到 docker compose 或 docker-compose 命令"
     fi
     log "检测到的 Compose 命令: $DC"
    $DC -f "$COMPOSE" config >/dev/null
    $DC -f "$COMPOSE" up -d --build
  else
    docker compose -f "$COMPOSE" config >/dev/null
  fi
else
  SERVICE="/etc/systemd/system/gemini-web2api.service"
  if [[ ! -f "$SERVICE" ]]; then
    [[ -f "$BUNDLE_DIR/gemini-web2api.service.example" ]] || fail "bundle 缺少 API service 模板"
    [[ $CHECK_ONLY -eq 1 ]] && fail "缺少 systemd API service：$SERVICE"
    cp "$BUNDLE_DIR/gemini-web2api.service.example" "$SERVICE"
    python3 - "$SERVICE" "$RUN_USER" "$API_DIR" "$VENV_DIR" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
user, api_dir, venv_dir = sys.argv[2:]
s = p.read_text(encoding='utf-8')
s = s.replace('User=root', f'User={user}', 1)
s = s.replace('WorkingDirectory=/opt/gemini-web2api', f'WorkingDirectory={api_dir}', 1)
s = s.replace('/opt/gemini-export-venv/bin/python', f'{venv_dir}/bin/python', 1)
s = s.replace('/opt/gemini-web2api/config.json', f'{api_dir}/config.json', 1)
p.write_text(s, encoding='utf-8')
PY
  fi
  if [[ $CHECK_ONLY -eq 0 ]]; then
    systemctl daemon-reload
    systemctl enable --now gemini-web2api.service
    systemctl restart gemini-web2api.service
    systemctl is-active --quiet gemini-web2api.service || fail "API service 启动失败"
  fi
fi

if [[ $INSTALL_WATCHDOG -eq 1 ]]; then
  [[ -f "$BUNDLE_DIR/gemini-cookie-watchdog.service.example" ]] || fail "bundle 缺少 watchdog service 模板"
  [[ -f "$BUNDLE_DIR/gemini-cookie-watchdog.timer.example" ]] || fail "bundle 缺少 watchdog timer 模板"
  if [[ $CHECK_ONLY -eq 0 ]]; then
    mkdir -p /var/lib/gemini-web2api
    if [[ ! -f /etc/default/gemini-cookie-watchdog ]]; then
      cp "$BUNDLE_DIR/gemini-cookie-watchdog.env.example" /etc/default/gemini-cookie-watchdog
    fi
    cp "$BUNDLE_DIR/gemini-cookie-watchdog.service.example" /etc/systemd/system/gemini-cookie-watchdog.service
    cp "$BUNDLE_DIR/gemini-cookie-watchdog.timer.example" /etc/systemd/system/gemini-cookie-watchdog.timer
    chmod 700 "$BUNDLE_DIR/gemini-cookie-watchdog-runner.sh"
    systemctl daemon-reload
    systemctl enable --now gemini-cookie-watchdog.timer
    systemctl start gemini-cookie-watchdog.service || log "watchdog 首次检查失败；查看 auth_lost/error 状态，不伪报成功"
  fi
fi

if [[ $CHECK_ONLY -eq 0 ]]; then
  mkdir -p "$API_DIR"
  chmod 755 "$API_DIR"
  [[ -f "$API_DIR/cookie.txt" ]] && chmod 600 "$API_DIR/cookie.txt"
fi

# Functional probe: use the configured key but never print it or response data.
if [[ $CHECK_ONLY -eq 0 ]]; then
  if ! systemctl is-active --quiet gemini-web2api.service; then
    fail "API service 未运行，跳过功能探测"
  fi

  "$PYTHON_BIN" - "$CONFIG" <<'PY'
import json, sys, urllib.request
from pathlib import Path
cfg = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
key = (cfg.get('api_keys') or [None])[0]
req = urllib.request.Request('http://127.0.0.1:8081/v1/models')
if key:
    req.add_header('Authorization', 'Bearer ' + str(key))
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read(2000).decode('utf-8', errors='replace')
        if r.status != 200 or not body.lstrip().startswith('{'):
            raise SystemExit(f'API probe returned non-JSON/non-200: {r.status}')
except Exception as exc:
    raise SystemExit(f'API functional probe failed: {exc}')
PY
fi

log "repair complete: mode=$MODE api_dir=$API_DIR venv=$VENV_DIR watchdog=$INSTALL_WATCHDOG"
