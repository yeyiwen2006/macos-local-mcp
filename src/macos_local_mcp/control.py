"""Local-only controls. Resume and command approval are never MCP tools."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from .commands import Commands
from .guard import Guard


def set_commands_enabled(guard: Guard, enabled: bool) -> None:
    """Atomic local approval; disabling does not follow a marker symlink."""
    marker = guard.state / "COMMANDS_ENABLED"
    if not enabled:
        marker.unlink(missing_ok=True)
        return
    if marker.is_symlink():
        raise ValueError("Command approval marker must not be a symlink")
    fd, name = tempfile.mkstemp(prefix=".commands-", dir=guard.state)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("Local operator approved current-user command execution.\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Local operator control for macOS Local MCP")
    parser.add_argument("action", choices=["pause", "resume", "status", "enable-commands", "disable-commands"])
    parser.add_argument("--accept-command-risk", action="store_true",
                        help="Explicitly accept current-user command execution without an OS sandbox")
    args = parser.parse_args(argv)
    if args.action == "enable-commands" and not args.accept_command_risk:
        parser.error("Enabling commands requires --accept-command-risk (or Enable-Commands.command)")
    guard = Guard()
    if args.action == "pause":
        guard.pause()
        print("Paused. Running operations and command groups stop at the next checkpoint.")
    elif args.action == "resume":
        guard.paused_file.unlink(missing_ok=True)
        print("Resumed. Previously cancelled commands are not restarted.")
    elif args.action in ("enable-commands", "disable-commands"):
        enabled = args.action == "enable-commands"
        set_commands_enabled(guard, enabled)
        print("Commands enabled with current-user permissions; not an OS sandbox."
              if enabled else "Commands disabled; running command groups will be stopped.")
    else:
        print(json.dumps({
            **guard.status(),
            "commands": {"enabled": Commands(guard).enabled, "requires_local_opt_in": True},
            "state_directory": str(guard.state),
            "note": "Local controls only, not Tunnel health or remote job counts.",
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
