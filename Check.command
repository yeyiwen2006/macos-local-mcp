#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
echo "== Local state =="
if [ -x ".venv/bin/python" ]; then
  MACOS_LOCAL_MCP_STATE="$PWD/.local" .venv/bin/python -m macos_local_mcp.control status
  .venv/bin/python -m macos_local_mcp.permissions || true
else
  echo "Not installed yet."
fi

echo
echo "== Tunnel =="
if [ -f ".local/running.json" ]; then
  PID="$(python3 -c 'import json; print(json.load(open(".local/running.json"))["pid"])')"
  HEALTH="$(python3 -c 'import json; print(json.load(open(".local/running.json"))["health_file"])')"
  if kill -0 "$PID" 2>/dev/null; then
    echo "Tunnel PID: $PID"
    if [ -f "$HEALTH" ]; then
      URL="$(cat "$HEALTH")"
      echo "Health URL: $URL"
      python3 - "$URL" <<'PY' || true
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=2) as r:
        print('Tunnel readiness HTTP', r.status)
except Exception as exc:
    print('Health check failed:', exc)
PY
    fi
  else
    echo "Recorded Tunnel is not running."
  fi
else
  echo "No running Tunnel recorded."
fi
