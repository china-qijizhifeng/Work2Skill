#!/usr/bin/env bash
#
# 一键启动 WorkRecorder + VM DOM/event hit 低延迟采集（含坐标变换）。
#
# 做的事：
#   1) 起到宿主机的基础隧道（2222=guest SSH / 5000=Control API / 5901=VNC）
#   2) 起 DOM hit / event-watch 隧道（本地 7071/7072 -> guest:7071/7072）
#   3) 注入 VM 屏幕几何 + event-watch 服务地址
#   4) 杀掉旧 daemon/app，直接启动 app 二进制（这样 daemon 继承到 env）
#
# 用法:  bash scripts/start_workrecorder_vm_a11y.sh
#        打开权限设置: bash scripts/start_workrecorder_vm_a11y.sh --open-permissions
#        关闭隧道:  bash scripts/start_workrecorder_vm_a11y.sh --stop
set -euo pipefail

# ---------- 可调参数（按你的 VM 实测值）----------
REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MYPCBENCH_SCRIPTS_DEV="${MYPCBENCH_SCRIPTS_DEV:-$HOME/MyPCBench/scripts_dev}"
APP_BIN="$REPO/dist/WorkRecorder.app/Contents/MacOS/WorkRecorder"
RUNTIME_CONFIG="$REPO/dist/WorkRecorder.app/Contents/Resources/runtime-config.json"
REPO_DOM_KEY="$REPO/scripts/persist-introspection/a11y_id_ed25519"
MYPCBENCH_DOM_KEY="${MYPCBENCH_SCRIPTS_DEV}/persist-introspection/a11y_id_ed25519"
DOM_KEY="${DOM_KEY:-$HOME/.ssh/persist_key}" # guest 私钥；repo key 存在时会优先使用
if [[ -f "$REPO_DOM_KEY" ]]; then
  DOM_KEY="$REPO_DOM_KEY"
elif [[ -f "$MYPCBENCH_DOM_KEY" ]]; then
  DOM_KEY="$MYPCBENCH_DOM_KEY"
fi
GUEST_USER="user"                          # guest 登录名
DEV_HOST="${WORKRECORDER_VM_HOST:-vm-host}"                          # ~/.ssh/config 里的宿主机别名
LOCAL_DOM_PORT="${LOCAL_DOM_PORT:-7071}"     # 本地 dom_at_point 映射端口
GUEST_DOM_PORT=7071                         # guest 上 DOM hit 服务端口
LOCAL_EVENT_PORT="${LOCAL_EVENT_PORT:-7072}" # 本地 event-watch 映射端口
LOCAL_EVENT_FALLBACK_PORT="${LOCAL_EVENT_FALLBACK_PORT:-17072}"
GUEST_EVENT_PORT=7072                       # guest 上 event-watch 服务端口
LOCAL_CLICK_LOG_PORT="${LOCAL_CLICK_LOG_PORT:-7073}" # 本地 click-log HTTP 映射端口
LOCAL_CLICK_LOG_FALLBACK_PORT="${LOCAL_CLICK_LOG_FALLBACK_PORT:-17073}"
LOCAL_CLICK_LOG_EXTRA_PORTS="${LOCAL_CLICK_LOG_EXTRA_PORTS:-27073 37073 47073}"
REMOTE_CLICK_LOG_PORT="${REMOTE_CLICK_LOG_PORT:-7073}" # Linux host 上 mirror-clicks HTTP 端口
REMOTE_CLICK_LOG_START_CMD="${REMOTE_CLICK_LOG_START_CMD:-}"
CLICK_LOG_GUEST_PATH="${CLICK_LOG_GUEST_PATH:-/tmp/clicks.jsonl}"
CLICK_LOG_FALLBACK_PATH="${WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_CLICK_LOG_PATH:-${MYPCBENCH_SCRIPTS_DEV}/persist-introspection/clicks.jsonl}"
CLICK_LOG_URL="${WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_CLICK_LOG_URL:-${CLICK_LOG_URL:-}}"

VM_SCREEN_WIDTH=1380
VM_SCREEN_HEIGHT=866
VM_TITLE_BAR_PT=27

VM_A11Y_REQUEST_TIMEOUT_SECONDS=2

# 记录完整 key down/up；系统层面的输入监听/辅助功能权限仍需手动授权给 WorkRecorder.app。
RECORD_FULL_KEYSTROKES=1
PYTHON_BIN="$REPO/.venv/bin/python"
APP_DATA_ROOT="$HOME/.workrecorder/app-dev"
# ------------------------------------------------

port_up() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
show_port_listeners() { lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null || true; }
dom_endpoint_up() {
  curl -fsS -m 3 "http://127.0.0.1:${LOCAL_DOM_PORT}/dom_at_point?x=1&y=1" >/dev/null 2>&1
}
event_endpoint_up_for_port() {
  local port="$1"
  curl -fsS -m 3 "http://127.0.0.1:${port}/health" >/dev/null 2>&1
}
event_endpoint_up() {
  event_endpoint_up_for_port "$LOCAL_EVENT_PORT"
}
click_log_endpoint_up_for_port() {
  local port="$1"
  curl -fsS -m 3 "http://127.0.0.1:${port}/health" >/dev/null 2>&1
}
click_log_endpoint_up() {
  click_log_endpoint_up_for_port "$LOCAL_CLICK_LOG_PORT"
}
remote_click_log_endpoint_up() {
  ssh -o ConnectTimeout=5 "$DEV_HOST" \
    "curl -fsS -m 2 http://127.0.0.1:${REMOTE_CLICK_LOG_PORT}/health >/dev/null" >/dev/null 2>&1
}

start_remote_click_log_service() {
  if remote_click_log_endpoint_up; then
    echo "[clicks] Linux host click-log 服务正常（${DEV_HOST}:127.0.0.1:${REMOTE_CLICK_LOG_PORT}）"
    return 0
  fi
  echo "[clicks] Linux host click-log 未响应，尝试启动 mirror-clicks.sh…"
  if [[ -n "$REMOTE_CLICK_LOG_START_CMD" ]]; then
    ssh "$DEV_HOST" "$REMOTE_CLICK_LOG_START_CMD"
    return
  fi
  ssh "$DEV_HOST" "REMOTE_CLICK_LOG_PORT='${REMOTE_CLICK_LOG_PORT}' GUEST_USER='${GUEST_USER}' bash -lc '
    if curl -fsS -m 2 \"http://127.0.0.1:\${REMOTE_CLICK_LOG_PORT}/health\" >/dev/null 2>&1; then
      exit 0
    fi
    for script in \
      \"\$HOME/MyPCBench/scripts/persist-introspection/mirror-clicks.sh\" \
      \"\$HOME/MyPCBench/scripts_dev/persist-introspection/mirror-clicks.sh\"
    do
      if [ -f \"\$script\" ]; then
        dir=\$(dirname \"\$script\")
        cd \"\$dir\" || exit 1
        HOST=127.0.0.1 PORT=2222 GUSER=\"\${GUEST_USER}\" nohup bash \"\$script\" >/tmp/mirror-clicks-http.log 2>&1 < /dev/null &
        exit 0
      fi
    done
    echo \"mirror-clicks.sh not found on Linux host\" >&2
    exit 1
  '"
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

stop_ssh_listener_for_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN -a -c ssh 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "[tunnel] 关闭占用 ${port} 的旧 ssh 隧道: ${pids}"
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

choose_event_port_if_occupied() {
  if ! port_up "$LOCAL_EVENT_PORT"; then
    return
  fi
  if event_endpoint_up; then
    return
  fi
  echo "[tunnel] ${LOCAL_EVENT_PORT} 已占用但不是 event-watch 服务："
  show_port_listeners "$LOCAL_EVENT_PORT"
  stop_ssh_listener_for_port "$LOCAL_EVENT_PORT"
  if ! port_up "$LOCAL_EVENT_PORT"; then
    return
  fi
  if [[ "$LOCAL_EVENT_PORT" != "$LOCAL_EVENT_FALLBACK_PORT" ]]; then
    if port_up "$LOCAL_EVENT_FALLBACK_PORT"; then
      if event_endpoint_up_for_port "$LOCAL_EVENT_FALLBACK_PORT"; then
        echo "[tunnel] ${LOCAL_EVENT_PORT} 被非 ssh 进程占用，复用健康的 fallback event-watch（${LOCAL_EVENT_FALLBACK_PORT}）"
        LOCAL_EVENT_PORT="$LOCAL_EVENT_FALLBACK_PORT"
        return
      fi
      echo "[tunnel] fallback ${LOCAL_EVENT_FALLBACK_PORT} 已占用但不是 event-watch 服务："
      show_port_listeners "$LOCAL_EVENT_FALLBACK_PORT"
      stop_ssh_listener_for_port "$LOCAL_EVENT_FALLBACK_PORT"
    fi
    if ! port_up "$LOCAL_EVENT_FALLBACK_PORT"; then
      echo "[tunnel] ${LOCAL_EVENT_PORT} 仍被非 ssh 进程占用，改用本地端口 ${LOCAL_EVENT_FALLBACK_PORT} -> guest:${GUEST_EVENT_PORT}"
      LOCAL_EVENT_PORT="$LOCAL_EVENT_FALLBACK_PORT"
      return
    fi
  fi
  echo "[event] ❌ event-watch 本地端口被占用，且 fallback ${LOCAL_EVENT_FALLBACK_PORT} 也不可用。请关闭上面占用进程，或指定 LOCAL_EVENT_PORT=其他端口。"
  exit 1
}

choose_click_log_port_if_occupied() {
  if ! port_up "$LOCAL_CLICK_LOG_PORT"; then
    return
  fi
  if click_log_endpoint_up; then
    return
  fi
  echo "[tunnel] ${LOCAL_CLICK_LOG_PORT} 已占用但不是 click-log 服务："
  show_port_listeners "$LOCAL_CLICK_LOG_PORT"
  stop_ssh_listener_for_port "$LOCAL_CLICK_LOG_PORT"
  if ! port_up "$LOCAL_CLICK_LOG_PORT"; then
    return
  fi
  local candidate
  for candidate in $LOCAL_CLICK_LOG_FALLBACK_PORT $LOCAL_CLICK_LOG_EXTRA_PORTS; do
    if [[ "$candidate" == "$LOCAL_CLICK_LOG_PORT" ]]; then
      continue
    fi
    if port_up "$candidate"; then
      if click_log_endpoint_up_for_port "$candidate"; then
        echo "[tunnel] ${LOCAL_CLICK_LOG_PORT} 被非 ssh 进程占用，复用健康的 click-log（${candidate}）"
        LOCAL_CLICK_LOG_PORT="$candidate"
        return
      fi
      echo "[tunnel] fallback ${candidate} 已占用但不是 click-log 服务："
      show_port_listeners "$candidate"
      stop_ssh_listener_for_port "$candidate"
      if port_up "$candidate"; then
        continue
      fi
    fi
    echo "[tunnel] ${LOCAL_CLICK_LOG_PORT} 仍被非 ssh 进程占用，改用本地端口 ${candidate} -> ${DEV_HOST}:127.0.0.1:${REMOTE_CLICK_LOG_PORT}"
    LOCAL_CLICK_LOG_PORT="$candidate"
    return
  done
  echo "[clicks] ❌ click-log 本地端口被占用，候选端口也不可用：${LOCAL_CLICK_LOG_FALLBACK_PORT} ${LOCAL_CLICK_LOG_EXTRA_PORTS}"
  exit 1
}

open_permissions_settings() {
  echo "[perm] 由 WorkRecorder 触发 macOS 权限提示。请允许 Accessibility，并在 Input Monitoring 中勾选 WorkRecorder。"
  osascript -e 'quit app "WorkRecorder"' 2>/dev/null || true
  sleep 1
  WORKRECORDER_REQUEST_PERMISSIONS_ON_LAUNCH=1 "$APP_BIN" --request-permissions >/tmp/workrecorder-permissions.log 2>&1 &
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" >/dev/null 2>&1 || true
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent" >/dev/null 2>&1 || true
  echo "[perm] 如果列表里有多个 WorkRecorder，请删除旧项，只保留：$APP_BIN"
  echo "       权限辅助日志: /tmp/workrecorder-permissions.log"
}

stop_all() {
  echo "[stop] 关闭隧道与 daemon…"
  pkill -f "L ${LOCAL_DOM_PORT}:127.0.0.1:${GUEST_DOM_PORT}" 2>/dev/null || true
  pkill -f "L ${LOCAL_EVENT_PORT}:127.0.0.1:${GUEST_EVENT_PORT}" 2>/dev/null || true
  pkill -f "L ${LOCAL_EVENT_FALLBACK_PORT}:127.0.0.1:${GUEST_EVENT_PORT}" 2>/dev/null || true
  pkill -f "L ${LOCAL_CLICK_LOG_PORT}:127.0.0.1:${REMOTE_CLICK_LOG_PORT}" 2>/dev/null || true
  pkill -f "L ${LOCAL_CLICK_LOG_FALLBACK_PORT}:127.0.0.1:${REMOTE_CLICK_LOG_PORT}" 2>/dev/null || true
  local candidate
  for candidate in $LOCAL_CLICK_LOG_EXTRA_PORTS; do
    pkill -f "L ${candidate}:127.0.0.1:${REMOTE_CLICK_LOG_PORT}" 2>/dev/null || true
  done
  pkill -f "services.context_daemon.main" 2>/dev/null || true
  echo "[stop] 完成（基础 ${DEV_HOST} 隧道与 app 未动，需要的话手动处理）"
}

if [[ "${1:-}" == "--stop" ]]; then
  stop_all
  exit 0
fi

if [[ "${1:-}" == "--open-permissions" ]]; then
  open_permissions_settings
  exit 0
fi

# ---------- 1. 基础隧道（2222/5000/5901）----------
if port_up 2222; then
  echo "[tunnel] 基础隧道已在（2222）"
else
  echo "[tunnel] 启动基础 ${DEV_HOST} 隧道 (2222/5000/5901)…"
  ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 \
    -L 5000:127.0.0.1:5000 -L 5901:127.0.0.1:5901 -L 2222:127.0.0.1:2222 "$DEV_HOST"
fi

# ---------- 2. DOM hit 隧道（7071 -> guest:7071）----------
if port_up "$LOCAL_DOM_PORT" && dom_endpoint_up; then
  echo "[tunnel] DOM hit 隧道已在（${LOCAL_DOM_PORT}）"
else
  if port_up "$LOCAL_DOM_PORT"; then
    echo "[tunnel] ${LOCAL_DOM_PORT} 已占用但不是 DOM hit 服务，准备重建隧道…"
    stop_ssh_listener_for_port "$LOCAL_DOM_PORT"
  fi
  echo "[tunnel] 启动 DOM hit 隧道 (${LOCAL_DOM_PORT} -> guest:${GUEST_DOM_PORT})…"
  ssh -i "$DOM_KEY" -p 2222 -f -N \
    -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 \
    -L "${LOCAL_DOM_PORT}:127.0.0.1:${GUEST_DOM_PORT}" "${GUEST_USER}@127.0.0.1"
fi

# ---------- 3. event-watch 隧道（7072 -> guest:7072）----------
choose_event_port_if_occupied
if port_up "$LOCAL_EVENT_PORT" && event_endpoint_up; then
  echo "[tunnel] event-watch 隧道已在（${LOCAL_EVENT_PORT}）"
else
  if port_up "$LOCAL_EVENT_PORT"; then
    echo "[tunnel] ${LOCAL_EVENT_PORT} 已占用但不是 event-watch 服务，准备重建隧道…"
    stop_ssh_listener_for_port "$LOCAL_EVENT_PORT"
  fi
  echo "[tunnel] 启动 event-watch 隧道 (${LOCAL_EVENT_PORT} -> guest:${GUEST_EVENT_PORT})…"
  ssh -i "$DOM_KEY" -p 2222 -f -N \
    -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 \
    -L "127.0.0.1:${LOCAL_EVENT_PORT}:127.0.0.1:${GUEST_EVENT_PORT}" "${GUEST_USER}@127.0.0.1"
fi

# ---------- 3b. DOM click-log HTTP 隧道（7073 -> Linux host:7073）----------
if [[ -z "$CLICK_LOG_URL" ]]; then
  if ! start_remote_click_log_service; then
    echo "[clicks] ⚠️  自动启动 Linux host click-log 失败；仍会尝试建立 tunnel 后探活。"
  fi
  choose_click_log_port_if_occupied
  if port_up "$LOCAL_CLICK_LOG_PORT" && click_log_endpoint_up; then
    echo "[tunnel] click-log 隧道已在（${LOCAL_CLICK_LOG_PORT}）"
  else
    if port_up "$LOCAL_CLICK_LOG_PORT"; then
      echo "[tunnel] ${LOCAL_CLICK_LOG_PORT} 已占用但不是 click-log 服务，准备重建隧道…"
      stop_ssh_listener_for_port "$LOCAL_CLICK_LOG_PORT"
    fi
    echo "[tunnel] 启动 click-log 隧道 (${LOCAL_CLICK_LOG_PORT} -> ${DEV_HOST}:127.0.0.1:${REMOTE_CLICK_LOG_PORT})…"
    ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 \
      -L "127.0.0.1:${LOCAL_CLICK_LOG_PORT}:127.0.0.1:${REMOTE_CLICK_LOG_PORT}" "$DEV_HOST"
  fi
  for _ in $(seq 1 20); do
    if click_log_endpoint_up; then
      break
    fi
    sleep 0.25
  done
  CLICK_LOG_URL="http://127.0.0.1:${LOCAL_CLICK_LOG_PORT}/clicks?n=5000"
fi

# ---------- 4. 探活 ----------
if dom_endpoint_up; then
  echo "[dom] 服务正常（127.0.0.1:${LOCAL_DOM_PORT}）"
else
  echo "[dom] ⚠️  ${LOCAL_DOM_PORT}/dom_at_point 无响应——检查 guest 上的 DOM hit 服务是否在跑"
fi
if event_endpoint_up; then
  echo "[event] 服务正常（127.0.0.1:${LOCAL_EVENT_PORT}）"
else
  echo "[event] ❌ ${LOCAL_EVENT_PORT}/health 无响应。WorkRecorder 不会启动到坏的 event-watch 配置。"
  echo "        请检查 guest 上 event-watch 是否在跑，或手动验证：curl -i http://127.0.0.1:${LOCAL_EVENT_PORT}/health"
  exit 1
fi
if [[ "$CLICK_LOG_URL" == "http://127.0.0.1:${LOCAL_CLICK_LOG_PORT}/clicks"* ]]; then
  if click_log_endpoint_up; then
    echo "[clicks] 服务正常（127.0.0.1:${LOCAL_CLICK_LOG_PORT}）"
  else
    echo "[clicks] ❌ ${LOCAL_CLICK_LOG_PORT}/health 无响应。WorkRecorder 不会启动到无 DOM click-log 配置。"
    echo "         请在 Linux host 上启动 mirror-clicks HTTP 服务，或手动验证：curl -i http://127.0.0.1:${REMOTE_CLICK_LOG_PORT}/health"
    exit 1
  fi
fi
if [[ -n "$CLICK_LOG_URL" ]]; then
  echo "[clicks] DOM click log 将由 daemon 导出时读取 HTTP 接口：$CLICK_LOG_URL"
else
  echo "[clicks] 未配置 DOM click log HTTP 接口；仅使用 event-watch/a11y。"
  echo "         可设置 CLICK_LOG_URL=http://<linux-host>:<port>/<path> 后重启。"
fi

# ---------- 5. 注入 env（开启坐标变换 + 指向 event-watch 隧道）----------
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_ENABLED=true
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_SOURCE="event_watch"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_URL="http://127.0.0.1:${LOCAL_EVENT_PORT}"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_A11Y_PATH="/dom_at_point"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_EVENTS_PATH="/events"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_EVENTS_LIMIT="20"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_CLICK_LOG_URL="$CLICK_LOG_URL"
export WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_CLICK_LOG_PATH="$CLICK_LOG_FALLBACK_PATH"
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

echo "[perm] 键鼠事件需要 macOS Accessibility + Input Monitoring 授权。脚本已开启完整 keylog 参数，但不能替你授予系统权限。"
echo "       如果键盘仍少字，请运行: bash scripts/start_workrecorder_vm_a11y.sh --open-permissions"

# ---------- 6. 重启 daemon + app（脚本先起 daemon，再起 app）----------
echo "[app] 停止旧 daemon / app…"
pkill -f "services.context_daemon.main" 2>/dev/null || true
osascript -e 'quit app "WorkRecorder"' 2>/dev/null || true
sleep 1

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[daemon] ❌ 未找到 Python 运行时：$PYTHON_BIN"
  exit 1
fi
echo "[daemon] 启动 daemon（继承 VM a11y env）…"
/usr/bin/python3 - "$REPO" "$PYTHON_BIN" "/tmp/workrecorder-daemon.log" <<'PY'
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
echo "[daemon] 等待 daemon 健康并校验 VM a11y 配置…"
for _ in $(seq 1 40); do
  if curl -fsS -m 1 "${WORKRECORDER_DAEMON_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if ! curl -fsS -m 2 "${WORKRECORDER_DAEMON_URL}/health" >/dev/null 2>&1; then
  echo "[daemon] ❌ daemon 未在 ${WORKRECORDER_DAEMON_URL} 变为健康。WorkRecorder 不会启动到无 a11y 校验状态。"
  echo "         daemon 日志: /tmp/workrecorder-daemon.log"
  echo "         app 日志: /tmp/workrecorder-app.log"
  exit 1
fi

TOKEN_RESPONSE="$(
  curl -fsS -m 3 -X POST "${WORKRECORDER_DAEMON_URL}/v1/auth/tokens" \
    -H "Content-Type: application/json" \
    -H "X-WorkRecorder-Install-Secret: ${WORKRECORDER_INSTALL_SECRET}" \
    --data '{"actor_id":"workrecorder-start-script","display_name":"WorkRecorder start script","scopes":["read_metadata"]}'
)"
DAEMON_TOKEN="$(printf '%s' "$TOKEN_RESPONSE" | json_stdin_field "data.access_token")"
if [[ -z "$DAEMON_TOKEN" ]]; then
  echo "[daemon] ❌ daemon token 获取失败，无法校验 VM a11y 配置。"
  exit 1
fi

VM_A11Y_SETTINGS="$(
  curl -fsS -m 3 "${WORKRECORDER_DAEMON_URL}/v1/settings/vm-a11y-probe" \
    -H "Authorization: Bearer ${DAEMON_TOKEN}"
)"
VM_A11Y_ENABLED="$(printf '%s' "$VM_A11Y_SETTINGS" | json_stdin_field "data.enabled")"
VM_A11Y_SOURCE="$(printf '%s' "$VM_A11Y_SETTINGS" | json_stdin_field "data.source")"
VM_A11Y_URL="$(printf '%s' "$VM_A11Y_SETTINGS" | json_stdin_field "data.url")"
VM_A11Y_CLICK_LOG_URL="$(printf '%s' "$VM_A11Y_SETTINGS" | json_stdin_field "data.click_log_url")"
EXPECTED_VM_A11Y_URL="http://127.0.0.1:${LOCAL_EVENT_PORT}"
if [[ "$VM_A11Y_ENABLED" != "True" || "$VM_A11Y_SOURCE" != "event_watch" || "$VM_A11Y_URL" != "$EXPECTED_VM_A11Y_URL" || "$VM_A11Y_CLICK_LOG_URL" != "$CLICK_LOG_URL" ]]; then
  echo "[daemon] ❌ VM a11y 配置不正确，拒绝继续。"
  echo "         expected: enabled=True source=event_watch url=${EXPECTED_VM_A11Y_URL} click_log_url=${CLICK_LOG_URL}"
  echo "         actual:   enabled=${VM_A11Y_ENABLED} source=${VM_A11Y_SOURCE} url=${VM_A11Y_URL} click_log_url=${VM_A11Y_CLICK_LOG_URL}"
  echo "         app 日志: /tmp/workrecorder-app.log"
  exit 1
fi
echo "[daemon] VM a11y 配置正常：source=${VM_A11Y_SOURCE} url=${VM_A11Y_URL} click_log_url=${VM_A11Y_CLICK_LOG_URL}"

echo "[app] 启动 WorkRecorder（复用已校验 daemon）…"
"$APP_BIN" >/tmp/workrecorder-app.log 2>&1 &

sleep 3
if ! curl -fsS -m 2 "${WORKRECORDER_DAEMON_URL}/health" >/dev/null 2>&1; then
  echo "[daemon] ❌ app 启动后 daemon 失联，拒绝继续录制。"
  echo "         daemon 日志: /tmp/workrecorder-daemon.log"
  echo "         app 日志: /tmp/workrecorder-app.log"
  exit 1
fi
VM_A11Y_SETTINGS_AFTER_APP="$(
  curl -fsS -m 3 "${WORKRECORDER_DAEMON_URL}/v1/settings/vm-a11y-probe" \
    -H "Authorization: Bearer ${DAEMON_TOKEN}"
)"
VM_A11Y_SOURCE_AFTER_APP="$(printf '%s' "$VM_A11Y_SETTINGS_AFTER_APP" | json_stdin_field "data.source")"
VM_A11Y_URL_AFTER_APP="$(printf '%s' "$VM_A11Y_SETTINGS_AFTER_APP" | json_stdin_field "data.url")"
VM_A11Y_CLICK_LOG_URL_AFTER_APP="$(printf '%s' "$VM_A11Y_SETTINGS_AFTER_APP" | json_stdin_field "data.click_log_url")"
if [[ "$VM_A11Y_SOURCE_AFTER_APP" != "event_watch" || "$VM_A11Y_URL_AFTER_APP" != "$EXPECTED_VM_A11Y_URL" || "$VM_A11Y_CLICK_LOG_URL_AFTER_APP" != "$CLICK_LOG_URL" ]]; then
  echo "[daemon] ❌ app 启动后 VM a11y 配置漂移，拒绝继续录制。"
  echo "         expected: source=event_watch url=${EXPECTED_VM_A11Y_URL} click_log_url=${CLICK_LOG_URL}"
  echo "         actual:   source=${VM_A11Y_SOURCE_AFTER_APP} url=${VM_A11Y_URL_AFTER_APP} click_log_url=${VM_A11Y_CLICK_LOG_URL_AFTER_APP}"
  exit 1
fi

echo "[done] 已启动。坐标变换 ON：${VM_SCREEN_WIDTH}x${VM_SCREEN_HEIGHT} titlebar=${VM_TITLE_BAR_PT}，event=127.0.0.1:${LOCAL_EVENT_PORT}/events"
echo "       click DOM hit enabled; click_log=${CLICK_LOG_URL}; full_keys=${RECORD_FULL_KEYSTROKES}"
echo "       daemon 日志: /tmp/workrecorder-daemon.log"
echo "       app 日志: /tmp/workrecorder-app.log"
