#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "Run ./Setup.command first." >&2
  exit 1
fi
echo "macOS controls privacy permission prompts; this script cannot grant permissions by itself."
echo "Grant Accessibility and Screen Recording to the terminal/host process that runs this service."
MACOS_LOCAL_MCP_STATE="$PWD/.local" .venv/bin/python -m macos_local_mcp.permissions --request
echo
echo "If you changed a privacy permission, restart the Terminal/host app and the MCP service."
