"""Operator stop, serialized actions, and content-free local audit records."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from . import __version__

PROJECT = Path(__file__).resolve().parents[2]


def state_directory() -> Path:
    return Path(os.environ.get("MACOS_LOCAL_MCP_STATE", str(PROJECT / ".local"))).absolute()


class Guard:
    def __init__(self, state: Path | None = None):
        raw_state = state or state_directory()
        if raw_state.is_symlink():
            raise ValueError("State directory must not be a symlink")
        self.state = raw_state.resolve()
        if (
            self.state == Path(self.state.anchor)
            or self.state == Path.home()
            or self.state == PROJECT
            or self.state in PROJECT.parents
        ):
            raise ValueError("State must be a dedicated service directory")
        marker = self.state / ".macos-local-mcp-state"
        if (
            self.state.exists()
            and self.state != PROJECT / ".local"
            and not marker.exists()
            and any(self.state.iterdir())
        ):
            raise ValueError("Refusing to use an existing non-service directory as state")
        self.state.mkdir(parents=True, exist_ok=True)
        try:
            self.state.chmod(0o700)
        except OSError:
            pass
        marker.write_text("macos-local-mcp\n", encoding="utf-8")
        try:
            marker.chmod(0o600)
        except OSError:
            pass
        self.paused_file = self.state / "PAUSED"
        self.stopped = threading.Event()
        self.lock = threading.RLock()
        self.hotkey_ready = False
        self.hotkey_error = "No global hotkey is registered by design; use Pause.command or service_pause"

    def check(self) -> None:
        if self.stopped.is_set() or self.paused_file.exists():
            raise PermissionError("Service paused locally. The operator must resume it on this Mac.")

    def pause(self) -> dict:
        self.stopped.set()
        self.paused_file.write_text("paused\n", encoding="utf-8")
        try:
            self.paused_file.chmod(0o600)
        except OSError:
            pass
        self.stopped.clear()
        return {"paused": True}

    def status(self) -> dict:
        return {
            "version": __version__,
            "experimental": True,
            "paused": self.stopped.is_set() or self.paused_file.exists(),
            "permissions": "all local files accessible to the current macOS user; desktop input additionally requires Accessibility",
            "transport": "stdio only; authenticate the remote caller using Secure MCP Tunnel",
            "emergency_pause": "Pause.command or service_pause",
            "hotkey_registered": self.hotkey_ready,
            "hotkey_error": self.hotkey_error,
            "audit_directory": str(self.state / "audit"),
            "backup_directory": str(self.state / "backups"),
        }

    def audit(self, record: dict) -> None:
        folder = self.state / "audit"
        folder.mkdir(exist_ok=True)
        try:
            folder.chmod(0o700)
        except OSError:
            pass
        now = datetime.now(timezone.utc)
        record = {"utc": now.isoformat(), **record}
        path = folder / f"{now:%Y-%m-%d}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
        try:
            path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def action(self, name: str, metadata: dict | None = None):
        with self.lock:
            self.check()
            event = {"id": uuid4().hex, "tool": name, **(metadata or {})}
            self.audit({**event, "result": "started"})
            try:
                yield
            except BaseException as exc:
                self.audit({**event, "result": "failed", "error_type": type(exc).__name__})
                raise
            else:
                self.audit({**event, "result": "completed"})

    def start_hotkey(self) -> None:
        # Deliberately avoid a global event tap: registering one can introduce an
        # additional Input Monitoring privacy surface. Pause.command remains local,
        # and service_pause remains available to the authenticated MCP caller.
        self.hotkey_ready = False

    def close(self) -> None:
        return None
