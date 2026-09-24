"""Window-bounds input clamping, window-scoped capture, and sandboxed commands."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_desktop import FakeBackend, MONITORS  # noqa: E402

from macos_local_mcp.commands import (_private_environment, seatbelt_prefix,  # noqa: E402
                                      SEATBELT_PROFILES)
from macos_local_mcp.desktop import Desktop, DesktopError  # noqa: E402


def locked_window(tmp_bounds=(0, 0, 800, 600)):
    backend = FakeBackend()
    desktop = Desktop(lambda: None, backend=backend)
    desktop.focus_window(10)
    return desktop, backend


def test_click_inside_window_bounds_passes():
    desktop, backend = locked_window()
    desktop.click(400, 300)
    assert ("button", 400, 300, "left", True) in backend.events


@pytest.mark.parametrize("x, y", [(850, 300), (400, 650), (-10, 100)])
def test_click_outside_window_bounds_is_rejected(x, y):
    # On-monitor but outside the locked window (0..800, 0..600): the menu bar,
    # the dock, and gaps beside the window are all reachable without bounds checks.
    desktop, backend = locked_window()
    with pytest.raises(DesktopError, match="outside the locked target window"):
        desktop.click(x, y)
    assert not any(event[0] == "button" for event in backend.events)
    # No stray pointer move either: nothing was sent.
    assert not any(event[0] == "move" for event in backend.events)


def test_drag_endpoints_must_both_be_inside():
    desktop, _backend = locked_window()
    with pytest.raises(DesktopError, match="outside"):
        desktop.drag(10, 10, 900, 10, 0.05)


def test_scroll_and_move_check_bounds_too():
    desktop, backend = locked_window()
    with pytest.raises(DesktopError, match="outside"):
        desktop.scroll(1700, 1000, vertical=2)
    assert not any(event[0] == "scroll" for event in backend.events)
    with pytest.raises(DesktopError, match="outside"):
        desktop.move(1000, 100)
    assert not any(event[0] == "move" for event in backend.events)


def test_window_scoped_screenshot_uses_window_capture():
    desktop, backend = locked_window()
    data, meta = desktop.screenshot(target_window=True)
    assert data.startswith(b"\x89PNG")
    assert meta["window_scoped"] is True
    assert backend.events[-1] == ("capture_window", 10)
    # full-screen capture still available and marks itself
    data, meta = desktop.screenshot()
    assert meta["window_scoped"] is False


def test_window_scoped_screenshot_requires_target():
    backend = FakeBackend()
    desktop = Desktop(lambda: None, backend=backend)
    with pytest.raises(DesktopError, match="No desktop input target"):
        desktop.screenshot(target_window=True)


def test_bounds_are_refetched_when_window_moves():
    desktop, backend = locked_window()
    backend._windows[0]["left"] = 100
    backend._windows[0]["right"] = 900
    desktop.click(850, 300)  # inside new bounds
    with pytest.raises(DesktopError):
        desktop.click(50, 300)  # now outside


def test_env_filter_blocks_credentials_but_keeps_build_paths():
    for name in ("GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY",
                 "ANTHROPIC_API_KEY", "STRIPE_KEY", "OPENAI_API_KEY"):
        assert _private_environment(name), name
    for name in ("PATH", "HOME", "LANG", "VIRTUAL_ENV", "SHELL", "TMPDIR", "SSH_AUTH_SOCK"):
        assert not _private_environment(name), name


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")
def test_seatbelt_read_only_blocks_writes_and_cleans_profile():
    prefix = seatbelt_prefix("/tmp", "read-only")
    profile = Path(prefix[2])
    assert profile.read_text(encoding="utf-8").startswith("(version 1)")
    from macos_local_mcp.commands import PosixProcess
    import time as _time
    proc = PosixProcess("/bin/sh", ["-c", "echo x > /tmp/mcp-sb-should-not-exist"],
                        "/tmp", dict(os.environ), sandbox_argv=prefix)
    proc.process.wait(timeout=10)
    proc.close()
    assert not Path("/tmp/mcp-sb-should-not-exist").exists()
    assert not profile.exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")
def test_seatbelt_workspace_write_allows_cwd_blocks_home_and_tmp():
    import tempfile
    import time as _time
    cwd = tempfile.mkdtemp(prefix="mcp-sb-cwd-")
    prefix = seatbelt_prefix(cwd, "workspace-write")
    from macos_local_mcp.commands import PosixProcess
    proc = PosixProcess(
        "/bin/sh",
        ["-c", "echo in > ./in.txt; echo out > /tmp/mcp-sb-outside; echo home > ~/.mcp-sb-home; true"],
        cwd, dict(os.environ), sandbox_argv=prefix)
    proc.process.wait(timeout=10)
    proc.close()
    assert (Path(cwd) / "in.txt").exists()
    assert not Path("/tmp/mcp-sb-outside").exists()
    assert not (Path.home() / ".mcp-sb-home").exists()


def test_sandbox_validation_rejects_unknown_profile():
    from macos_local_mcp.commands import Commands
    from macos_local_mcp.guard import Guard
    import tempfile
    commands = Commands(Guard(Path(tempfile.mkdtemp()) / "state"))
    with pytest.raises(ValueError, match="sandbox"):
        commands.start("/usr/bin/true", [], "/tmp", sandbox="hardened-network")
    assert commands.status()["sandbox_profiles"] == sorted(SEATBELT_PROFILES)


def test_network_flag_requires_sandbox():
    from macos_local_mcp.commands import Commands
    from macos_local_mcp.guard import Guard
    import tempfile
    commands = Commands(Guard(Path(tempfile.mkdtemp()) / "state"))
    with pytest.raises(ValueError, match="network"):
        commands.start("/usr/bin/true", [], "/tmp", network=True)


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")
def test_seatbelt_workspace_write_with_network_reaches_dns():
    import socket  # noqa: F401
    import tempfile
    cwd = tempfile.mkdtemp(prefix="mcp-sb-net-")
    prefix = seatbelt_prefix(cwd, "workspace-write", network=True)
    from macos_local_mcp.commands import PosixProcess
    proc = PosixProcess(
        "/usr/bin/dscacheutil", ["-q", "host", "-a", "name", "localhost"],
        cwd, dict(os.environ), sandbox_argv=prefix)
    proc.process.wait(timeout=15)
    out = os.read(proc.process.stdout.fileno(), 65536).decode(errors="replace")
    proc.close()
    assert "localhost" in out, "network-enabled sandbox could not even resolve localhost"


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")
def test_seatbelt_workspace_write_without_network_blocks_dns():
    import tempfile
    cwd = tempfile.mkdtemp(prefix="mcp-sb-nonet-")
    prefix = seatbelt_prefix(cwd, "workspace-write", network=False)
    from macos_local_mcp.commands import PosixProcess
    proc = PosixProcess(
        "/usr/bin/dscacheutil", ["-q", "host", "-a", "name", "example.com"],
        cwd, dict(os.environ), sandbox_argv=prefix)
    proc.process.wait(timeout=15)
    out = os.read(proc.process.stdout.fileno(), 65536).decode(errors="replace")
    proc.close()
    assert "example.com" not in out, "default sandbox unexpectedly resolved a public host"
