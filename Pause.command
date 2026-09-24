#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  mkdir -p .local
  printf 'paused\n' > .local/PAUSED
  chmod 600 .local/PAUSED
else
  MACOS_LOCAL_MCP_STATE="$PWD/.local" .venv/bin/python -m macos_local_mcp.control pause
fi
