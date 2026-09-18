#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p .local
chmod 700 .local

read -r -p "Tunnel ID: " TUNNEL_ID
case "$TUNNEL_ID" in
  tunnel_*) ;;
  *) echo "Invalid Tunnel ID." >&2; exit 1 ;;
esac

read -r -s -p "Runtime API key (hidden): " RUNTIME_KEY
echo
if [ -z "$RUNTIME_KEY" ]; then
  echo "Empty runtime key is not allowed." >&2
  exit 1
fi

python3 - "$TUNNEL_ID" <<'PY'
import json, os, sys
path = os.path.join('.local', 'connection.json')
with open(path, 'w', encoding='utf-8') as f:
    json.dump({'tunnel_id': sys.argv[1]}, f)
os.chmod(path, 0o600)
PY

security add-generic-password -U -s "macos-local-mcp-runtime" -a "$USER" -w "$RUNTIME_KEY" >/dev/null
unset RUNTIME_KEY
echo "Saved Tunnel ID locally and runtime key in macOS Keychain."
