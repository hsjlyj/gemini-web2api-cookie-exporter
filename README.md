# Gemini Web Cookie 一键导出器

给 [`Sophomoresty/gemini-web2api`](https://github.com/Sophomoresty/gemini-web2api) 使用。

## 使用

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
python3 export_gemini_cookie.py --output-dir /path/to/gemini-web2api
```

如果项目目录里已有 `config.json`，脚本会自动更新：

- `cookie_file`
- `auth_user`
- `xsrf_token`（捕获成功时）
- `gemini_bl`（捕获成功时）

同时生成：

```text
/path/to/gemini-web2api/cookie.txt
```

首次运行会打开一个**独立 Chrome 配置目录**，在窗口中完成 Google/Gemini 登录；之后重新运行即可再次导出，不会读取或修改你的主浏览器配置。

如果云服务器已有登录过 Google 的 Chrome Profile，可以指定已有的 `user-data-dir`：

```bash
PYTHON_BIN=/opt/gemini-export-venv/bin/python \
  ./cloud-login-export.sh \
  --profile-dir /root/.config/google-chrome \
  --profile-directory Default \
  --output-dir /opt/gemini-web2api
```

如果账号在 `Profile 1`、`Profile 2` 等目录，把 `--profile-directory` 改成对应名称。使用已有 Profile 前必须先关闭正在运行的 Chrome，否则会遇到 Profile 锁定或浏览器启动失败。

## 云服务器部署

云服务器通常没有可见桌面，使用内置的 Xvfb + x11vnc + noVNC。VNC/noVNC 只监听 `127.0.0.1`，通过 SSH 隧道访问，不要把 5900/6080 暴露到公网。

### 1. 安装依赖

```bash
apt-get update
apt-get install -y xvfb x11vnc novnc websockify python3 python3-venv

python3 -m venv /opt/gemini-export-venv
/opt/gemini-export-venv/bin/pip install playwright
/opt/gemini-export-venv/bin/python -m playwright install chromium
```

### 2. 启动云端登录导出

```bash
cd /opt/gemini-web2api-cookie-exporter

# 直接使用虚拟环境执行：
PYTHON_BIN=/opt/gemini-export-venv/bin/python \
  ./cloud-login-export.sh --output-dir /opt/gemini-web2api

# Docker 场景：容器内路径通常是 /app/cookie.txt
PYTHON_BIN=/opt/gemini-export-venv/bin/python \
  ./cloud-login-export.sh \
  --output-dir /opt/gemini-web2api \
  --config-cookie-file /app/cookie.txt

# 或者先激活虚拟环境后执行：
. /opt/gemini-export-venv/bin/activate
./cloud-login-export.sh --output-dir /opt/gemini-web2api
```

### 自动检测、补齐与修复

缺包、venv、Playwright、项目目录、配置、Docker Cookie 挂载、API 服务或 watchdog 有问题时，使用 repair 入口：

```bash
cd /opt/gemini-web2api-cookie-exporter

# 只检测，不修改：
./repair-gemini-web2api-cloud.sh \
  --mode auto \
  --api-dir /opt/gemini-web2api \
  --venv /opt/gemini-export-venv \
  --check-only

# 自动安装缺失依赖、修复服务并做真实 API 探测：
./repair-gemini-web2api-cloud.sh \
  --mode auto \
  --api-dir /opt/gemini-web2api \
  --venv /opt/gemini-export-venv
```

它不会覆盖已有配置、删除项目数据、生成假密钥或绕过 Google 登录。缺少 Cookie、`auth_lost`、验证码和二次验证仍需通过 noVNC 手动处理。

### 3. 本地建立 SSH 隧道

保持服务器上的导出命令运行，另开本地终端：

```bash
ssh -N -L 6080:127.0.0.1:6080 root@服务器IP
```

本地浏览器打开：

```text
http://127.0.0.1:6080/vnc.html
```

在 noVNC 窗口中完成 Google/Gemini 登录。脚本检测到登录 Cookie 后会自动写出 `cookie.txt` 并更新配置。

## 定时检测与自动刷新

新增 `gemini_cookie_watchdog.py`。它会定期启动同一个云端 Chrome Profile：

- Gemini 登录仍然有效：重新读取可能已轮换的 Cookie、`xsrf_token`、`gemini_bl`
- Cookie/配置发生变化：自动写回文件
- Cookie 文件变化：`gemini-web2api` 下次请求会按 mtime 自动重新读取
- `xsrf_token` 或 `gemini_bl` 变化：可通过 `RESTART_COMMAND` 自动重启 API
- Google 真正登出、要求验证码或二次验证：记录 `auth_lost`，不会尝试自动输入密码/绕过验证

### 安装 systemd 定时器

```bash
cd /opt/gemini-web2api-cookie-exporter
cp gemini-cookie-watchdog.env.example /etc/default/gemini-cookie-watchdog
cp gemini-cookie-watchdog.service.example /etc/systemd/system/gemini-cookie-watchdog.service
cp gemini-cookie-watchdog.timer.example /etc/systemd/system/gemini-cookie-watchdog.timer
chmod 700 gemini-cookie-watchdog-runner.sh

systemctl daemon-reload
systemctl enable --now gemini-cookie-watchdog.timer
systemctl start gemini-cookie-watchdog.service
```

默认每 **4 小时**检查一次。查看状态：

```bash
systemctl list-timers gemini-cookie-watchdog.timer
systemctl status gemini-cookie-watchdog.service
journalctl -u gemini-cookie-watchdog.service -n 50 --no-pager
cat /var/lib/gemini-web2api/watchdog-state.json
```

如果 API 是 Docker 容器，编辑 `/etc/default/gemini-cookie-watchdog`，确认：

```bash
OUTPUT_DIR=/opt/gemini-web2api
CONFIG_COOKIE_FILE=/app/cookie.txt
```

如果 `xsrf_token` 或 `gemini_bl` 变化后需要重启 API，在 env 文件里设置实际命令，例如：

```bash
RESTART_COMMAND=systemctl\ restart\ gemini-web2api.service
```

或：

```bash
RESTART_COMMAND=docker\ compose\ -f\ /opt/gemini-web2api/docker-compose.yml\ restart
```

### 重要限制

这个功能是**自动刷新仍然有效的登录会话**，不是自动完成 Google 重新登录。若 Google 已经撤销会话，定时器会显示 `auth_lost`；此时通过同一个 Profile 使用 noVNC 手动登录一次，后续定时刷新会自动恢复。

如果项目目录没有 `config.json`，默认生成 `gemini-export.json` 配置补丁；也可以强制创建：

```bash
python3 export_gemini_cookie.py \
  --output-dir /path/to/gemini-web2api \
  --write-config
```

### 测试脚本自身

```bash
python3 export_gemini_cookie.py --self-test
python3 gemini_cookie_watchdog.py --self-test
```

## 开发与测试

本项目核心逻辑已收敛到 `gemini_export/_common.py`（Cookie 筛选、XSRF/`gemini_bl` 提取、文件 I/O、浏览器发现），并共享 `build_launch_args()` 和 `add_common_export_args()` 两个工具函数，两个主脚本仅保留各自流程控制。

建议使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install playwright
python3 -m playwright install chromium
```

运行单测：

```bash
python3 -m unittest tests.test_gemini_export -v
python3 -m unittest tests.test_watchdog -v
python3 -m unittest tests.test_browser_helpers -v
```

或一次性运行全部测试：

```bash
python3 -m unittest discover -s tests -v
```

> 该项目已集成 RTK；示例中的 `rtk unittest discover`、`rtk git status`、`rtk git diff` 是可选的 token 优化前缀。

## RTK 集成

项目已配置 [RTK](https://github.com/rtk-ai/rtk)（Codex CLI）。在受支持的环境里，建议把可识别的 shell 命令加上 `rtk` 前缀：

```bash
rtk unittest discover
rtk git status
rtk git diff
```

### 建议提交说明

- `rtk: add codex integration`
- `docs: add rtk verification steps`

### 验收命令

```bash
rtk --version
rtk gain
rtk init --codex --show
rtk verify

## Headroom 集成

项目已集成 [Headroom](https://github.com/headroomlabs-ai/headroom) 作为可选的上下文压缩实验入口。当前仓库默认不自动安装其依赖；如需使用，请先准备可写环境或离线 wheelhouse。

### 安装

```bash
make headroom-install
```

安装目标会从本地 `HEADROOM_DIR` 创建 `.venv-headroom`，并尝试安装 `headroom-ai[all]`。如果网络不可用，请改为提供离线 wheelhouse，或确保 `HEADROOM_DIR` 中的依赖可被 `uv` / `pip` 解析。

### 使用

```bash
HEADROOM_DIR=/root/headroom ./scripts/headroom --help
HEADROOM_VENV=.venv-headroom ./scripts/headroom compress --help
```

### 验收

```bash
make headroom
```

### 建议提交说明

- `chore: add headroom integration`
- `docs: add headroom install notes`

代码风格：

- Python 3.11+
- 4 空格缩进
- 保留现有中文注释与错误提示
- 不要在日志或异常中打印敏感值

## 安全

`cookie.txt` 和 `gemini-export.json` 含登录凭证/XSRF 信息，脚本在 Linux/macOS 上设置为 `600` 权限。不要提交 Git、上传网盘或发给他人。建议把以下内容加入项目 `.gitignore`：

```gitignore
cookie.txt
gemini-export.json
config.json

# 本地浏览器配置 / Profile
chrome-profile/

# watchdog 状态文件
/var/lib/gemini-web2api/watchdog-state.json

# 运行时生成的备份文件
*.bak
```

脚本不会打印 Cookie 或 Token 的值，也不会读取已有 Chrome 主配置目录。
