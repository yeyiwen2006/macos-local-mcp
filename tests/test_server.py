from __future__ import annotations

import time

import pytest

from macos_local_mcp.guard import Guard
from macos_local_mcp.server import Runtime, build_server
from macos_local_mcp.desktop import DesktopError


class FakeDesktop:
    def __init__(self):
        self.expected_foreground_hwnd = None
        self.allowed = True

    def foreground_window(self):
        return 10

    def validate_input_target(self, hwnd):
        if not self.allowed:
            raise DesktopError("locked")
        assert hwnd == 10
        return {"window_id": 10}

    def permission_status(self):
        return {"accessibility": True, "screen_recording": True}

    def target_summary(self):
        return {"window_id": 10, "pid": 100, "title": "Editor"}


def test_observation_is_recent_single_use_and_target_checked(tmp_path):
    runtime = Runtime(Guard(tmp_path / "state"))
    fake = FakeDesktop()
    runtime._desktop = fake

    with pytest.raises(ValueError):
        runtime.observed_input("missing")

    runtime.observation = {"id": "ok", "time": time.monotonic(), "foreground_hwnd": 10}
    runtime.observed_input("ok")
    assert fake.expected_foreground_hwnd == 10

    with pytest.raises(ValueError):
        runtime.observed_input("ok")

    runtime.observation = {"id": "old", "time": time.monotonic() - 61, "foreground_hwnd": 10}
    with pytest.raises(ValueError, match="expired"):
        runtime.observed_input("old")

    fake.allowed = False
    runtime.observation = {"id": "blocked", "time": time.monotonic(), "foreground_hwnd": 10}
    with pytest.raises(DesktopError, match="locked"):
        runtime.observed_input("blocked")


def test_server_builds_without_loading_native_desktop(tmp_path):
    server, runtime = build_server(Guard(tmp_path / "state"))
    assert server is not None
    assert runtime._desktop is None
