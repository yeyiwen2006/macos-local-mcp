#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
while true; do
  echo
  echo "macOS Local MCP"
  echo "1  Configure Tunnel"
  echo "2  Request/check macOS permissions"
  echo "3  Start"
  echo "4  Check"
  echo "5  Pause"
  echo "6  Resume"
  echo "7  Stop"
  echo "8  Setup/repair"
  echo "9  Exit"
  echo "10 Enable local commands (explicit approval)"
  echo "11 Disable local commands"
  read -r -p "> " choice
  case "$choice" in
    1) ./Configure.command ;;
    2) ./Permissions.command ;;
    3) ./Start.command ;;
    4) ./Check.command ;;
    5) ./Pause.command ;;
    6) ./Resume.command ;;
    7) ./Stop.command ;;
    8) ./Setup.command ;;
    9) exit 0 ;;
    10) ./Enable-Commands.command ;;
    11) ./Disable-Commands.command ;;
    *) echo "Unknown choice." ;;
  esac
done
