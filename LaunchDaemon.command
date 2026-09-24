#!/bin/bash
# LaunchAgent entry point: start the tunnel daemon if not already running.
# KeepAlive restarts it when it exits nonzero; this script makes each start idempotent.
set -euo pipefail
cd "$HOME/ZCodeProject/macos-local-mcp"

# Skip if a verified instance is already running (same check Start.command uses).
if [ -f .local/running.json ] && .venv/bin/python -c '
import json, os, psutil
try:
    r = json.load(open(".local/running.json", encoding="utf-8"))
    p = psutil.Process(int(r["pid"]))
    ok = (abs(float(p.create_time()) - float(r["create_time"])) < 0.01
          and os.path.realpath(p.exe()) == os.path.realpath(r["executable"]))
except Exception:
    ok = False
raise SystemExit(0 if ok else 1)
'; then
  exit 0
fi
rm -f .local/running.json

TUNNEL="$(find .local/tools -type f -name tunnel-client -perm -111 2>/dev/null | sort | tail -n 1)"
if [ -z "$TUNNEL" ]; then
  echo "tunnel-client missing; run Setup.command" >&2
  exit 1
fi
if [ ! -f .local/connection.json ]; then
  echo "not configured; run Configure.command" >&2
  exit 1
fi

TUNNEL_ID="$(python3 -c 'import json; print(json.load(open(".local/connection.json"))["tunnel_id"])')"
RUNTIME_KEY="$(security find-generic-password -s macos-local-mcp-runtime -a "$USER" -w)"

# Stale per-start health files + log rotation (same hygiene as Start.command).
find .local -maxdepth 1 -name 'health-*.url' -type f -delete 2>/dev/null || true
for log in .local/tunnel.stdout.log .local/tunnel.stderr.log; do
  if [ -f "$log" ] && [ "$(stat -f %z "$log" 2>/dev/null || echo 0)" -gt 10485760 ]; then
    mv "$log" "$log.1"
  fi
done
HEALTH_FILE="$PWD/.local/health-$(date +%s)-$$.url"

export CONTROL_PLANE_API_KEY="$RUNTIME_KEY"
export CONTROL_PLANE_TUNNEL_ID="$TUNNEL_ID"
export MCP_COMMAND="\"$PWD/.venv/bin/python\" -m macos_local_mcp"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export MACOS_LOCAL_MCP_STATE="$PWD/.local"

# Track our PID like Start.command does, so Check.command and Start.command
# recognize this launchd-managed instance instead of double-starting.
(
  sleep 0.2
  .venv/bin/python - "$$" "$TUNNEL" <<'PY'
import json, os, sys
import psutil
pid = int(sys.argv[1])
try:
    process = psutil.Process(pid)
    record = {
        'pid': pid,
        'create_time': process.create_time(),
        'executable': os.path.realpath(process.exe()),
        'health_file': '',
    }
    with open('.local/running.json', 'w', encoding='utf-8') as f:
        json.dump(record, f)
    os.chmod('.local/running.json', 0o600)
except psutil.Error:
    pass  # daemon exited; KeepAlive will retry and rewrite the record
PY
) &

exec "$TUNNEL" run \
  --health.listen-addr 127.0.0.1:0 \
  --health.url-file "$HEALTH_FILE" \
  --mcp.stdio-send-initialized-notification
