#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
./Pause.command || true
if [ ! -f ".local/running.json" ]; then
  echo "No recorded Tunnel process."
  exit 0
fi
PID="$(python3 -c 'import json; print(json.load(open(".local/running.json"))["pid"])')"
EXPECTED="$(python3 -c 'import json; print(json.load(open(".local/running.json"))["executable"])')"
if ! kill -0 "$PID" 2>/dev/null; then
  echo "Tunnel is already stopped."
  rm -f .local/running.json
  exit 0
fi
ACTUAL="$(ps -p "$PID" -o command= | awk '{print $1}')"
ACTUAL_REAL="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$ACTUAL")"
if [ "$ACTUAL_REAL" != "$EXPECTED" ]; then
  echo "Recorded process identity changed; refusing to stop another process." >&2
  exit 1
fi
kill "$PID"
for _ in $(seq 1 20); do
  kill -0 "$PID" 2>/dev/null || break
  sleep 0.1
done
if kill -0 "$PID" 2>/dev/null; then
  kill -KILL "$PID"
fi
rm -f .local/running.json
echo "Tunnel and its MCP child stopped."
