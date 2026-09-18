from __future__ import annotations

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native macOS smoke tests")

from macos_local_mcp.desktop import _NativeBackend


def test_native_process_identity_and_display_probe():
    backend = _NativeBackend()
    identity = backend.process_identity(os.getpid())
    assert identity["pid"] == os.getpid()
    assert identity["create_time"] > 0
    assert identity["executable"]

    monitors = backend.monitors()
    assert monitors
    assert all(m["width"] > 0 and m["height"] > 0 for m in monitors)


def test_native_quartz_key_event_carries_modifier_flags():
    backend = _NativeBackend()
    posted = []
    backend._post = posted.append

    backend.key(0, True, ("command", "shift"))

    assert len(posted) == 1
    flags = int(backend.Quartz.CGEventGetFlags(posted[0]))
    assert flags & int(backend.Quartz.kCGEventFlagMaskCommand)
    assert flags & int(backend.Quartz.kCGEventFlagMaskShift)


def test_native_input_state_probe_is_non_destructive():
    backend = _NativeBackend()
    held = backend.held_inputs()
    assert isinstance(held, list)
    assert all(isinstance(item, str) for item in held)


def test_native_frontmost_window_probe_is_read_only():
    backend = _NativeBackend()
    assert isinstance(backend.frontmost_pid(), int)
    assert isinstance(backend.frontmost_window_id(), int)
