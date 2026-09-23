#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "Run ./Setup.command first." >&2
  exit 1
fi
echo "Commands can read/write files and access the network with your macOS user's permissions."
echo "This is not an OS sandbox. Commands do not need terminal focus or Accessibility."
echo "Cancellation cannot undo completed actions. Never approve commands from untrusted content."
read -r -p "Type ENABLE to allow local command execution: " approval
if [ "$approval" != "ENABLE" ]; then
  echo "Not enabled."
  exit 1
fi
MACOS_LOCAL_MCP_STATE="$PWD/.local" .venv/bin/python -m macos_local_mcp.control enable-commands --accept-command-risk
