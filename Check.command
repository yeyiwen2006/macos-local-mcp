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
if [ -f ".local/running.json" ] && [ -x ".venv/bin/python" ]; then
  STATUS="$(
    .venv/bin/python - <<'PY'
import json, os
import psutil
try:
    record = json.load(open('.local/running.json', encoding='utf-8'))
    process = psutil.Process(int(record['pid']))
    same = (
        abs(float(process.create_time()) - float(record['create_time'])) < 0.01
        and os.path.realpath(process.exe()) == os.path.realpath(record['executable'])
    )
    if same:
        print(f"verified:{record['pid']}:{record['health_file']}")
    else:
        print('identity-mismatch')
except psutil.NoSuchProcess:
    print('not-running')
except Exception:
    print('invalid-record')
PY
  )"
  case "$STATUS" in
    verified:*)
      REST="${STATUS#verified:}"
      PID="${REST%%:*}"
      HEALTH="${REST#*:}"
      echo "Verified Tunnel PID: $PID"
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
      else
        echo "Health URL file is not available yet."
      fi
      ;;
    identity-mismatch)
      echo "Recorded PID exists but process identity does not match; refusing to trust it."
      ;;
    not-running)
      echo "Recorded Tunnel is not running."
      ;;
    *)
      echo "Running record is invalid or cannot be verified."
      ;;
  esac
else
  echo "No running Tunnel recorded."
fi
