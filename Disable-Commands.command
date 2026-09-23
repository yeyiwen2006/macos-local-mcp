#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  MACOS_LOCAL_MCP_STATE="$PWD/.local" .venv/bin/python -m macos_local_mcp.control disable-commands
else
  rm -f .local/COMMANDS_ENABLED
  echo "Commands disabled; running command groups will stop at the next checkpoint."
fi
