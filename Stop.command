#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
./Pause.command || true

if [ ! -f ".local/running.json" ]; then
  echo "No recorded Tunnel process."
  exit 0
fi
PYTHON="$PWD/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Python environment is missing; refusing an unverifiable stop." >&2
  exit 1
fi

"$PYTHON" - <<'PY'
import json, os, sys
import psutil
record = json.load(open('.local/running.json', encoding='utf-8'))
pid = int(record['pid'])
try:
    process = psutil.Process(pid)
except psutil.NoSuchProcess:
    print('Tunnel is already stopped.')
    raise SystemExit(0)
try:
    same = (
        abs(float(process.create_time()) - float(record['create_time'])) < 0.01
        and os.path.realpath(process.exe()) == os.path.realpath(record['executable'])
    )
except (OSError, psutil.Error, KeyError, ValueError):
    same = False
if not same:
    print('Recorded process identity changed; refusing to stop another process.', file=sys.stderr)
    raise SystemExit(2)
children = process.children(recursive=True)
targets = children + [process]
for target in targets:
    try:
        target.terminate()
    except psutil.NoSuchProcess:
        pass
_, alive = psutil.wait_procs(targets, timeout=2.0)
for target in alive:
    try:
        target.kill()
    except psutil.NoSuchProcess:
        pass
psutil.wait_procs(alive, timeout=2.0)
print('Verified Tunnel process tree stopped.')
PY

rm -f .local/running.json
echo "Tunnel and its MCP child stopped."
