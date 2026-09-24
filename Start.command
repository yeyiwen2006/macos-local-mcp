#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p .local
chmod 700 .local

PYTHON="$PWD/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Run ./Setup.command first." >&2
  exit 1
fi
if [ ! -f ".local/connection.json" ]; then
  echo "Run ./Configure.command first." >&2
  exit 1
fi

if [ -f ".local/running.json" ]; then
  if "$PYTHON" - <<'PY'
import json, os
import psutil
try:
    record = json.load(open('.local/running.json', encoding='utf-8'))
    process = psutil.Process(int(record['pid']))
    same = (
        abs(float(process.create_time()) - float(record['create_time'])) < 0.01
        and os.path.realpath(process.exe()) == os.path.realpath(record['executable'])
    )
except (OSError, ValueError, KeyError, psutil.Error):
    same = False
raise SystemExit(0 if same else 1)
PY
  then
    echo "Already running with a verified Tunnel process." >&2
    exit 1
  else
    rm -f .local/running.json
  fi
fi

TUNNEL="$(find .local/tools -type f -name tunnel-client -perm -111 2>/dev/null | sort | tail -n 1)"
if [ -z "$TUNNEL" ]; then
  echo "Tunnel client not found. Run ./Setup.command." >&2
  exit 1
fi

TUNNEL_ID="$(python3 -c 'import json; print(json.load(open(".local/connection.json"))["tunnel_id"])')"
RUNTIME_KEY="$(security find-generic-password -s "macos-local-mcp-runtime" -a "$USER" -w)"
# Remove stale per-start health URL files and rotate oversized tunnel logs.
find .local -maxdepth 1 -name 'health-*.url' -type f -delete 2>/dev/null || true
for log in .local/tunnel.stdout.log .local/tunnel.stderr.log; do
  if [ -f "$log" ] && [ "$(stat -f %z "$log" 2>/dev/null || echo 0)" -gt 10485760 ]; then
    mv "$log" "$log.1"
  fi
done
HEALTH_FILE="$PWD/.local/health-$(date +%s)-$$.url"

export CONTROL_PLANE_API_KEY="$RUNTIME_KEY"
export CONTROL_PLANE_TUNNEL_ID="$TUNNEL_ID"
export MCP_COMMAND="\"$PYTHON\" -m macos_local_mcp"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export MACOS_LOCAL_MCP_STATE="$PWD/.local"

nohup "$TUNNEL" run \
  --health.listen-addr 127.0.0.1:0 \
  --health.url-file "$HEALTH_FILE" \
  --mcp.stdio-send-initialized-notification \
  >.local/tunnel.stdout.log 2>.local/tunnel.stderr.log &
PID=$!
unset CONTROL_PLANE_API_KEY RUNTIME_KEY

"$PYTHON" - "$PID" "$TUNNEL" "$HEALTH_FILE" <<'PY'
import json, os, sys
import psutil
pid = int(sys.argv[1])
process = psutil.Process(pid)
record = {
    'pid': pid,
    'create_time': process.create_time(),
    'executable': os.path.realpath(process.exe()),
    'health_file': sys.argv[3],
}
with open('.local/running.json', 'w', encoding='utf-8') as f:
    json.dump(record, f)
os.chmod('.local/running.json', 0o600)
PY

for _ in $(seq 1 40); do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f .local/running.json
    echo "Tunnel client exited. Check .local/tunnel.stderr.log" >&2
    exit 1
  fi
  [ -f "$HEALTH_FILE" ] && break
  sleep 0.25
done

echo "Tunnel client started in the background with PID $PID."
./Check.command
