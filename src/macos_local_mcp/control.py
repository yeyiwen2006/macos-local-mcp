"""Local-only controls. Resume is intentionally not exported as an MCP tool."""
from __future__ import annotations

import argparse
import json

from .guard import state_directory


def main():
    parser = argparse.ArgumentParser(description="Local operator control for macOS Local MCP")
    parser.add_argument("action", choices=["pause", "resume", "status"])
    args = parser.parse_args()
    state = state_directory()
    state.mkdir(parents=True, exist_ok=True)
    paused = state / "PAUSED"
    if args.action == "pause":
        paused.write_text("paused\n", encoding="utf-8")
        try:
            paused.chmod(0o600)
        except OSError:
            pass
        print("Paused. Running operations stop at the next checkpoint.")
    elif args.action == "resume":
        paused.unlink(missing_ok=True)
        print("Resumed. Restart the service if an in-memory emergency stop was triggered.")
    else:
        print(json.dumps({
            "paused": paused.exists(),
            "state_directory": str(state),
            "note": "This reports the local pause marker, not Tunnel health.",
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
