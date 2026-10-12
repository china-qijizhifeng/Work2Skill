#!/usr/bin/env bash
#
# 从 Mac 通过用户已建立的 SSH 本地转发连接 OSWorld 镜像，探活后启动 WorkRecorder。
#
# 服务器公网只需开放 22/tcp。下列服务端口必须只监听 127.0.0.1：
#   12001-12010 guest SSH       15001-15010 Control API
#   15901-15910 VNC             17001-17010 clicks/events gateway
#   18001-18010 noVNC           18701-18710 Streamlit reset UI
#   18600 Reset Controller
#
# 默认使用槽位 01，先在一个终端建立隧道：
#   bash scripts/start_workrecorder_osworld_vm_a11y.sh --print-tunnel
#
# 再在另一个终端运行：
#   bash scripts/start_workrecorder_osworld_vm_a11y.sh --check
#   bash scripts/start_workrecorder_osworld_vm_a11y.sh
#
# 其他槽位示例：
#   OSWORLD_SLOT=02 bash scripts/start_workrecorder_osworld_vm_a11y.sh --print-tunnel
#   OSWORLD_SLOT=02 bash scripts/start_workrecorder_osworld_vm_a11y.sh
#
# 可调本地端口：LOCAL_VNC_PORT / LOCAL_GATEWAY_PORT / LOCAL_RESET_UI_PORT
# 可调坐标参数：VM_SCREEN_WIDTH / VM_SCREEN_HEIGHT / VM_TITLE_BAR_PT
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${WORKRECORDER_REPO_ROOT:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
APP_BIN="$REPO/dist/WorkRecorder.app/Contents/MacOS/WorkRecorder"
RUNTIME_CONFIG="$REPO/dist/WorkRecorder.app/Contents/Resources/runtime-config.json"
PYTHON_BIN="${PYTHON_BIN:-$REPO/.venv/bin/python}"
APP_DATA_ROOT="${WORKRECORDER_APP_DATA_ROOT:-$HOME/.workrecorder/app-dev}"

OSWORLD_SLOT_RAW="${OSWORLD_SLOT:-01}"
if [[ ! "$OSWORLD_SLOT_RAW" =~ ^(0?[1-9]|10)$ ]]; then
  echo "[config] ❌ OSWORLD_SLOT 必须是 01-10，当前值：$OSWORLD_SLOT_RAW"
  exit 2
fi
printf -v OSWORLD_SLOT "%02d" "$((10#$OSWORLD_SLOT_RAW))"
SLOT_NUMBER="$((10#$OSWORLD_SLOT))"

OSWORLD_SERVER="${OSWORLD_SERVER:-180.184.170.160}"
OSWORLD_SSH_USER="${OSWORLD_SSH_USER:-recording${OSWORLD_SLOT}}"
OSWORLD_SSH_KEY="${OSWORLD_SSH_KEY:-$HOME/.ssh/osworld-recording}"
REMOTE_VNC_PORT="$((15900 + SLOT_NUMBER))"
REMOTE_GATEWAY_PORT="$((17000 + SLOT_NUMBER))"
REMOTE_RESET_UI_PORT="$((18700 + SLOT_NUMBER))"

# 用户侧只访问 IPv6 loopback，与 --print-tunnel 生成的 -L '[::1]:...' 一致。
LOCAL_BIND_HOST="${LOCAL_BIND_HOST:-::1}"
LOCAL_VNC_PORT="${LOCAL_VNC_PORT:-5901}"
LOCAL_GATEWAY_PORT="${LOCAL_GATEWAY_PORT:-7073}"
LOCAL_RESET_UI_PORT="${LOCAL_RESET_UI_PORT:-8501}"
if [[ "$LOCAL_BIND_HOST" == *:* ]]; then
  LOCAL_HTTP_HOST="[$LOCAL_BIND_HOST]"
else
  LOCAL_HTTP_HOST="$LOCAL_BIND_HOST"
fi
GATEWAY_URL="http://${LOCAL_HTTP_HOST}:${LOCAL_GATEWAY_PORT}"
RESET_UI_URL="http://${LOCAL_HTTP_HOST}:${LOCAL_RESET_UI_PORT}"
CLICK_LOG_URL="${WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_CLICK_LOG_URL:-${CLICK_LOG_URL:-${GATEWAY_URL}/clicks?n=5000}}"

VM_SCREEN_WIDTH="${VM_SCREEN_WIDTH:-1920}"
VM_SCREEN_HEIGHT="${VM_SCREEN_HEIGHT:-1080}"
VM_TITLE_BAR_PT="${VM_TITLE_BAR_PT:-27}"
VM_A11Y_REQUEST_TIMEOUT_SECONDS="${VM_A11Y_REQUEST_TIMEOUT_SECONDS:-2}"
RECORD_FULL_KEYSTROKES="${RECORD_FULL_KEYSTROKES:-1}"

DAEMON_LOG="${DAEMON_LOG:-/tmp/workrecorder-osworld-daemon.log}"
APP_LOG="${APP_LOG:-/tmp/workrecorder-osworld-app.log}"

usage() {
  cat <<'EOF'
用法：
  bash scripts/start_workrecorder_osworld_vm_a11y.sh
  bash scripts/start_workrecorder_osworld_vm_a11y.sh --check
  bash scripts/start_workrecorder_osworld_vm_a11y.sh --print-tunnel
  bash scripts/start_workrecorder_osworld_vm_a11y.sh --open-permissions
  bash scripts/start_workrecorder_osworld_vm_a11y.sh --stop

说明：
  --check             只检查现有 SSH 隧道及后端健康，不启动 WorkRecorder。
  --print-tunnel      按 OSWORLD_SLOT 输出应在独立终端执行的 SSH 命令。
  --open-permissions  打开 macOS Accessibility / Input Monitoring 权限设置。
  --stop              只停止脚本启动的 WorkRecorder/daemon，不会关闭 SSH 隧道。
EOF
}

print_tunnel_command() {
  cat <<EOF
# 槽位 ${OSWORLD_SLOT}：公网只连 ${OSWORLD_SERVER}:22；服务端目标均为 loopback。
ssh -F /dev/null -N -T \\
  -o ExitOnForwardFailure=yes \\
  -o IdentitiesOnly=yes \\
  -i '${OSWORLD_SSH_KEY}' \\
  -L '[::1]:${LOCAL_VNC_PORT}:127.0.0.1:${REMOTE_VNC_PORT}' \\
  -L '[::1]:${LOCAL_GATEWAY_PORT}:127.0.0.1:${REMOTE_GATEWAY_PORT}' \\
  -L '[::1]:${LOCAL_RESET_UI_PORT}:127.0.0.1:${REMOTE_RESET_UI_PORT}' \\
  '${OSWORLD_SSH_USER}@${OSWORLD_SERVER}'
EOF
}

json_field() {
  local path="$1"
  local key="$2"
  /usr/bin/python3 - "$path" "$key" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    value = json.load(handle)
for part in sys.argv[2].split("."):
    if isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
        break
print("" if value is None else value)
PY
}

json_stdin_field() {
  local key="$1"
  /usr/bin/python3 -c '
import json
import sys

value = json.load(sys.stdin)
for part in sys.argv[1].split("."):
    if isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
        break
print("" if value is None else value)
' "$key"
}

vnc_endpoint_up() {
  local banner
  banner="$(/usr/bin/nc -w 2 "$LOCAL_BIND_HOST" "$1" </dev/null 2>/dev/null | /usr/bin/head -c 4 || true)"
  [[ "$banner" == "RFB " ]]
}

http_endpoint_up() {
  /usr/bin/curl -g -fsS --noproxy '*' --connect-timeout 2 -m 5 "$1" >/dev/null 2>&1
}

show_local_listener() {
  /usr/sbin/lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
}

show_tunnel_recovery() {
  echo
  echo "[tunnel] 请在另一个终端保持以下命令运行："
  print_tunnel_command
}

check_tunnel_health() {
  local failed=0

  echo "[check] OSWorld 槽位 ${OSWORLD_SLOT}，local=[${LOCAL_BIND_HOST}]"
  if vnc_endpoint_up "$LOCAL_VNC_PORT"; then
    echo "[vnc] ✅ [${LOCAL_BIND_HOST}]:${LOCAL_VNC_PORT} -> server 127.0.0.1:${REMOTE_VNC_PORT} RFB 服务就绪"
  else
    echo "[vnc] ❌ [${LOCAL_BIND_HOST}]:${LOCAL_VNC_PORT} 不可达"
    show_local_listener "$LOCAL_VNC_PORT"
    failed=1
  fi

  if http_endpoint_up "${GATEWAY_URL}/health"; then
    echo "[gateway] ✅ ${GATEWAY_URL}/health"
  else
    echo "[gateway] ❌ ${GATEWAY_URL}/health 无法返回 HTTP 2xx"
    show_local_listener "$LOCAL_GATEWAY_PORT"
    failed=1
  fi

  if http_endpoint_up "${GATEWAY_URL}/events?n=1"; then
    echo "[events] ✅ ${GATEWAY_URL}/events?n=1"
  else
    echo "[events] ❌ gateway 的 /events 接口不健康"
    failed=1
  fi

  if http_endpoint_up "${GATEWAY_URL}/clicks?n=1"; then
    echo "[clicks] ✅ ${GATEWAY_URL}/clicks?n=1"
  else
    echo "[clicks] ❌ gateway 的 /clicks 接口不健康"
    failed=1
  fi

  if http_endpoint_up "${RESET_UI_URL}/_stcore/health"; then
    echo "[reset-ui] ✅ ${RESET_UI_URL}/_stcore/health"
  else
    echo "[reset-ui] ❌ ${RESET_UI_URL}/_stcore/health 无法返回 HTTP 2xx"
    show_local_listener "$LOCAL_RESET_UI_PORT"
    failed=1
  fi

  if ((failed)); then
    echo "[check] ❌ SSH 隧道或 OSWorld 服务未完全就绪。WorkRecorder 不会启动到坏配置。"
    show_tunnel_recovery
    return 1
  fi

  echo "[check] ✅ VNC、clicks/events gateway 和 Streamlit 重置页均健康"
}

open_permissions_settings() {
  if [[ ! -x "$APP_BIN" ]]; then
    echo "[perm] ❌ 未找到 WorkRecorder app：$APP_BIN"
    exit 1
  fi
  echo "[perm] 请允许 Accessibility，并在 Input Monitoring 中勾选 WorkRecorder。"
  osascript -e 'quit app "WorkRecorder"' 2>/dev/null || true
  sleep 1
  WORKRECORDER_REQUEST_PERMISSIONS_ON_LAUNCH=1 "$APP_BIN" --request-permissions >"$APP_LOG" 2>&1 &
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" >/dev/null 2>&1 || true
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent" >/dev/null 2>&1 || true
  echo "[perm] 如果列表中有多个 WorkRecorder，请只保留：$APP_BIN"
}

stop_workrecorder() {
  echo "[stop] 停止 WorkRecorder app 和本地 daemon…"
  pkill -f "services.context_daemon.main" 2>/dev/null || true
  osascript -e 'quit app "WorkRecorder"' 2>/dev/null || true
  echo "[stop] 完成。SSH 隧道未动，可在其所在终端按 Ctrl-C 关闭。"
}

case "${1:-}" in
  --help|-h)
    usage
    exit 0
    ;;
  --print-tunnel)
    print_tunnel_command
    exit 0
    ;;
  --check)
    check_tunnel_health
    exit 0
    ;;
  --open-permissions)
    open_permissions_settings
    exit 0
    ;;
  --stop)
    stop_workrecorder
    exit 0
    ;;
  "")
    ;;
  *)
    echo "未知参数：$1" >&2
    usage >&2
    exit 2
    ;;
esac

# 先验证用户维护的 SSH 隧道，脚本不直连任何服务器内部端口。
check_tunnel_health

if [[ ! -x "$APP_BIN" ]]; then
  echo "[app] ❌ 未找到可执行的 WorkRecorder app：$APP_BIN"
  exit 1
fi
if [[ ! -f "$RUNTIME_CONFIG" ]]; then
  echo "[app] ❌ 未找到 runtime config：$RUNTIME_CONFIG"
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[daemon] ❌ 未找到 Python 运行时：$PYTHON_BIN"
  exit 1
fi

# 注入 OSWorld 1920x1080 坐标变换及本地 gateway 配置。
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_ENABLED=true
export WORKRECORDER_RECORDING_TARGET=linux
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_PROFILE="osworld_gateway_v1"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_SOURCE="event_watch"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_URL="$GATEWAY_URL"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_A11Y_PATH="/dom_at_point"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_EVENTS_PATH="/events"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_EVENTS_LIMIT="20"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_CLICK_LOG_URL="$CLICK_LOG_URL"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_CLICK_LOG_SSH_ENABLED=false
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_REQUEST_TIMEOUT_SECONDS="$VM_A11Y_REQUEST_TIMEOUT_SECONDS"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_VM_SCREEN_WIDTH="$VM_SCREEN_WIDTH"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_VM_SCREEN_HEIGHT="$VM_SCREEN_HEIGHT"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_TITLE_BAR_PT="$VM_TITLE_BAR_PT"
export WORKRECORDER_ACTIVE_CAPTURE_FULL_KEYSTROKES="$RECORD_FULL_KEYSTROKES"
export WORKRECORDER_REPO_ROOT="$REPO"
export WORKRECORDER_DAEMON_URL="${WORKRECORDER_DAEMON_URL:-$(json_field "$RUNTIME_CONFIG" "daemon_url")}"
export WORKRECORDER_DAEMON_URL="${WORKRECORDER_DAEMON_URL:-http://127.0.0.1:8765}"
export WORKRECORDER_INSTALL_SECRET="${WORKRECORDER_INSTALL_SECRET:-$(json_field "$RUNTIME_CONFIG" "install_secret")}"
export WORKRECORDER_PROVIDER_REGISTRATION_SECRET="${WORKRECORDER_PROVIDER_REGISTRATION_SECRET:-$(json_field "$RUNTIME_CONFIG" "provider_registration_secret")}"
export WORKRECORDER_NATIVE_CAPTURE_SECRET="${WORKRECORDER_NATIVE_CAPTURE_SECRET:-$(json_field "$RUNTIME_CONFIG" "native_capture_secret")}"
export WORKRECORDER_DATABASE_PATH="${WORKRECORDER_DATABASE_PATH:-$APP_DATA_ROOT/workrecorder.db}"
export WORKRECORDER_ARTIFACT_STAGING_DIR="${WORKRECORDER_ARTIFACT_STAGING_DIR:-$APP_DATA_ROOT/staging}"
export WORKRECORDER_ARTIFACT_VAULT_DIR="${WORKRECORDER_ARTIFACT_VAULT_DIR:-$APP_DATA_ROOT/artifacts}"
export WORKRECORDER_EXTERNAL_DAEMON=1
mkdir -p "$APP_DATA_ROOT" "$WORKRECORDER_ARTIFACT_STAGING_DIR" "$WORKRECORDER_ARTIFACT_VAULT_DIR"

echo "[perm] 键鼠事件需要 macOS Accessibility + Input Monitoring 授权。"
echo "       需要时运行：bash scripts/start_workrecorder_osworld_vm_a11y.sh --open-permissions"

echo "[app] 停止旧 daemon / app…"
pkill -f "services.context_daemon.main" 2>/dev/null || true
osascript -e 'quit app "WorkRecorder"' 2>/dev/null || true
sleep 1

echo "[daemon] 启动 daemon（继承 OSWorld a11y env）…"
/usr/bin/python3 - "$REPO" "$PYTHON_BIN" "$DAEMON_LOG" <<'PY'
import os
import subprocess
import sys

repo, python_bin, log_path = sys.argv[1:4]
log = open(log_path, "ab", buffering=0)
subprocess.Popen(
    [python_bin, "-m", "services.context_daemon.main"],
    cwd=repo,
    env=os.environ.copy(),
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
    close_fds=True,
)
PY

echo "[daemon] 等待 daemon 健康并校验 OSWorld a11y 配置…"
for _ in $(seq 1 40); do
  if /usr/bin/curl -fsS --noproxy '*' -m 1 "${WORKRECORDER_DAEMON_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if ! /usr/bin/curl -fsS --noproxy '*' -m 2 "${WORKRECORDER_DAEMON_URL}/health" >/dev/null 2>&1; then
  echo "[daemon] ❌ daemon 未在 ${WORKRECORDER_DAEMON_URL} 变为健康。"
  echo "         daemon 日志：$DAEMON_LOG"
  echo "         app 日志：$APP_LOG"
  exit 1
fi

TOKEN_RESPONSE="$(
  /usr/bin/curl -fsS --noproxy '*' -m 3 -X POST "${WORKRECORDER_DAEMON_URL}/v1/auth/tokens" \
    -H "Content-Type: application/json" \
    -H "X-WorkRecorder-Install-Secret: ${WORKRECORDER_INSTALL_SECRET}" \
    --data '{"actor_id":"workrecorder-osworld-start-script","display_name":"WorkRecorder OSWorld start script","scopes":["read_metadata"]}'
)"
DAEMON_TOKEN="$(printf '%s' "$TOKEN_RESPONSE" | json_stdin_field "data.access_token")"
if [[ -z "$DAEMON_TOKEN" ]]; then
  echo "[daemon] ❌ daemon token 获取失败，无法校验 OSWorld a11y 配置。"
  exit 1
fi

verify_daemon_vm_a11y() {
  local phase="$1"
  local settings enabled profile source url click_log_url
  settings="$(
    /usr/bin/curl -fsS --noproxy '*' -m 3 "${WORKRECORDER_DAEMON_URL}/v1/settings/vm-a11y-probe" \
      -H "Authorization: Bearer ${DAEMON_TOKEN}"
  )"
  enabled="$(printf '%s' "$settings" | json_stdin_field "data.enabled")"
  profile="$(printf '%s' "$settings" | json_stdin_field "data.profile")"
  source="$(printf '%s' "$settings" | json_stdin_field "data.source")"
  url="$(printf '%s' "$settings" | json_stdin_field "data.url")"
  click_log_url="$(printf '%s' "$settings" | json_stdin_field "data.click_log_url")"
  if [[ "$enabled" != "True" || "$profile" != "osworld_gateway_v1" || "$source" != "event_watch" || "$url" != "$GATEWAY_URL" || "$click_log_url" != "$CLICK_LOG_URL" ]]; then
    echo "[daemon] ❌ ${phase} OSWorld a11y 配置不正确，拒绝继续。"
    echo "         expected: enabled=True profile=osworld_gateway_v1 source=event_watch url=${GATEWAY_URL} click_log_url=${CLICK_LOG_URL}"
    echo "         actual:   enabled=${enabled} profile=${profile} source=${source} url=${url} click_log_url=${click_log_url}"
    return 1
  fi
  echo "[daemon] ✅ ${phase} OSWorld a11y 配置正常：profile=${profile} source=${source} url=${url}"
}

verify_daemon_vm_a11y "app 启动前"

echo "[app] 启动 WorkRecorder（复用已校验 daemon）…"
"$APP_BIN" >"$APP_LOG" 2>&1 &

sleep 3
if ! /usr/bin/curl -fsS --noproxy '*' -m 2 "${WORKRECORDER_DAEMON_URL}/health" >/dev/null 2>&1; then
  echo "[daemon] ❌ app 启动后 daemon 失联，拒绝继续录制。"
  echo "         daemon 日志：$DAEMON_LOG"
  echo "         app 日志：$APP_LOG"
  exit 1
fi
verify_daemon_vm_a11y "app 启动后"

# app 启动期间隧道也可能断开，完成前再检查一次。
check_tunnel_health

echo "[done] ✅ WorkRecorder 已连接 OSWorld 槽位 ${OSWORLD_SLOT}"
echo "       坐标变换：${VM_SCREEN_WIDTH}x${VM_SCREEN_HEIGHT}, titlebar=${VM_TITLE_BAR_PT}pt"
echo "       event：${GATEWAY_URL}/events"
echo "       clicks：${CLICK_LOG_URL}"
echo "       reset UI：${RESET_UI_URL}"
echo "       daemon 日志：$DAEMON_LOG"
echo "       app 日志：$APP_LOG"
echo
echo "========== 开始任务前，请按顺序操作 =========="
echo "1. Streamlit 工作台：在浏览器打开 ${RESET_UI_URL}，领取任务。"
echo "2. TigerVNC：打开 TigerVNC Viewer，Server 填写 [::1]::${LOCAL_VNC_PORT}（或 localhost::${LOCAL_VNC_PORT}）。"
echo "3. WorkRecorder：回到 WorkRecorder，点击“开始录制”；确认录制开始后，再在 TigerVNC 中执行任务。"
