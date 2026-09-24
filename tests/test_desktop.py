from __future__ import annotations

from io import BytesIO
import threading

import pytest
from PIL import Image

from macos_local_mcp.desktop import Desktop, DesktopError, _chord, _duration, _point, _region


MONITORS = [
    {"left": -1440, "top": 0, "right": 0, "bottom": 900},
    {"left": 0, "top": 0, "right": 1728, "bottom": 1117},
]


def png(width=200, height=100):
    image = Image.new("RGB", (width, height), "white")
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class FakeBackend:
    def __init__(self):
        self.front_pid = 100
        self.focused = {"window_id": 10, "title": "Editor", "modal": False}
        self.identity = {
            "pid": 100,
            "create_time": 123.0,
            "executable": "/Applications/Editor.app/Contents/MacOS/Editor",
            "bundle_id": "com.example.Editor",
        }
        self.events = []
        self.held = []
        self.accessibility = True
        self._windows = [
            {"hwnd": 10, "window_id": 10, "pid": 100, "title": "Editor",
             "left": 0, "top": 0, "right": 800, "bottom": 600, "foreground": True},
            {"hwnd": 20, "window_id": 20, "pid": 200, "title": "Chat",
             "left": 50, "top": 50, "right": 700, "bottom": 500, "foreground": False},
        ]

    def permission_status(self):
        return {"accessibility": True, "screen_recording": True}

    def monitors(self):
        return MONITORS

    def bounds(self):
        return (-1440, 0, 1728, 1117)

    def windows(self):
        return list(self._windows)

    def window_record(self, wid):
        return next(w for w in self._windows if w["window_id"] == wid)

    def frontmost_pid(self):
        return self.front_pid

    def frontmost_window_id(self):
        return int(self.focused["window_id"]) if self.front_pid else 0

    def process_identity(self, pid):
        if pid != self.identity["pid"]:
            raise DesktopError("missing")
        return dict(self.identity)

    def focused_window_signature(self, pid):
        if not self.accessibility:
            raise DesktopError("Accessibility permission is required")
        if pid != self.front_pid:
            return None
        return dict(self.focused)

    def focus_window(self, wid):
        record = self.window_record(wid)
        self.front_pid = record["pid"]
        self.focused = {"window_id": wid, "title": record["title"], "modal": False}
        if wid == 20:
            self.identity = {
                "pid": 200,
                "create_time": 456.0,
                "executable": "/Applications/Chat.app/Contents/MacOS/Chat",
                "bundle_id": "com.example.Chat",
            }
        return record

    def capture_png(self, bbox):
        self.events.append(("capture", bbox))
        return png(400, 200)

    def capture_window_png(self, window_id):
        self.events.append(("capture_window", window_id))
        return png(800, 600)

    def mouse_move(self, x, y):
        self.events.append(("move", x, y))

    def mouse_button(self, x, y, button, down):
        self.events.append(("button", x, y, button, down))

    def held_inputs(self):
        return list(self.held)

    def scroll(self, vertical, horizontal):
        self.events.append(("scroll", vertical, horizontal))

    def key(self, keycode, down, modifiers=()):
        self.events.append(("key", keycode, down, tuple(modifiers)))

    def unicode_text(self, text):
        self.events.append(("text", text))


def locked_desktop():
    backend = FakeBackend()
    desktop = Desktop(lambda: None, backend=backend)
    desktop.focus_window(10)
    return desktop, backend


def test_validation_helpers():
    assert _point(-100, 100, MONITORS) == (-100, 100)
    with pytest.raises(ValueError):
        _point(5000, 1, MONITORS)
    assert _region(None, (-1440, 0, 1728, 1117)) == (-1440, 0, 1728, 1117)
    with pytest.raises(ValueError):
        _region((0, 0, 0, 1), (-1440, 0, 1728, 1117))
    assert _duration(0.5) == 0.5
    with pytest.raises(ValueError):
        _duration(float("inf"))


def test_chord_normalizes_command_and_modifiers_first():
    chord = _chord(["a", "cmd", "SHIFT"])
    assert [item[0] for item in chord] == ["command", "shift", "a"]
    with pytest.raises(ValueError):
        _chord(["a", "b"])


def test_input_requires_explicit_target():
    backend = FakeBackend()
    desktop = Desktop(lambda: None, backend=backend)
    with pytest.raises(DesktopError, match="No desktop input target"):
        desktop.click(100, 100)


def test_screenshot_works_without_accessibility_when_screen_capture_backend_works():
    desktop, backend = locked_desktop()
    backend.accessibility = False
    data, meta = desktop.screenshot()
    assert data.startswith(b"\x89PNG")
    assert meta["foreground_hwnd"] == 10
    assert meta["input_allowed"] is False


def test_screenshot_never_retargets_after_user_switch():
    desktop, backend = locked_desktop()
    backend.front_pid = 200
    backend.focused = {"window_id": 20, "title": "Chat", "modal": False}
    data, meta = desktop.screenshot()
    assert data.startswith(b"\x89PNG")
    assert meta["input_target"]["window_id"] == 10
    assert meta["foreground_hwnd"] == 20
    assert meta["input_allowed"] is False
    with pytest.raises(DesktopError, match="locked"):
        desktop.click(100, 100)
    assert not any(event[0] == "button" for event in backend.events)


def test_switching_back_to_locked_window_allows_input():
    desktop, backend = locked_desktop()
    backend.front_pid = 200
    backend.focused = {"window_id": 20, "title": "Chat", "modal": False}
    with pytest.raises(DesktopError):
        desktop.click(100, 100)
    backend.front_pid = 100
    backend.focused = {"window_id": 10, "title": "Editor", "modal": False}
    result = desktop.click(100, 100)
    assert result["button"] == "left"
    assert ("button", 100, 100, "left", True) in backend.events
    assert ("button", 100, 100, "left", False) in backend.events


def test_modal_dialog_in_target_app_is_allowed():
    desktop, backend = locked_desktop()
    backend.focused = {"window_id": 11, "title": "Save", "modal": True}
    desktop.keypress(["command", "s"])
    assert any(event[0] == "key" for event in backend.events)


def test_unrelated_window_in_same_process_is_rejected():
    desktop, backend = locked_desktop()
    backend.focused = {"window_id": 12, "title": "Other document", "modal": False}
    with pytest.raises(DesktopError, match="locked"):
        desktop.keypress(["command", "s"])


def test_process_restart_invalidates_target():
    desktop, backend = locked_desktop()
    backend.identity["create_time"] = 999.0
    with pytest.raises(DesktopError, match="locked"):
        desktop.keypress(["enter"])


def test_keypress_sets_explicit_quartz_modifier_flags():
    desktop, backend = locked_desktop()
    desktop.keypress(["command", "shift", "a"])
    ordinary_down = next(
        event for event in backend.events
        if event[0] == "key" and event[1] == 0 and event[2] is True
    )
    assert set(ordinary_down[3]) == {"command", "shift"}


def test_held_user_input_must_be_stably_released(monkeypatch):
    desktop, backend = locked_desktop()
    now = {"value": 0.0}
    backend.held = ["Left Command"]

    def monotonic():
        return now["value"]

    def sleep(seconds):
        now["value"] += seconds
        if now["value"] >= 0.2:
            backend.held = []

    monkeypatch.setattr("macos_local_mcp.desktop.time.monotonic", monotonic)
    monkeypatch.setattr("macos_local_mcp.desktop.time.sleep", sleep)
    desktop.click(10, 10)
    assert now["value"] >= 0.3
    assert any(event[0] == "button" and event[4] is True for event in backend.events)


def test_persistent_held_input_blocks_without_sending_input(monkeypatch):
    desktop, backend = locked_desktop()
    now = {"value": 0.0}
    backend.held = ["Left Control", "Left mouse button"]

    monkeypatch.setattr("macos_local_mcp.desktop.time.monotonic", lambda: now["value"])
    monkeypatch.setattr(
        "macos_local_mcp.desktop.time.sleep",
        lambda seconds: now.__setitem__("value", now["value"] + seconds),
    )
    with pytest.raises(DesktopError, match="Left Control, Left mouse button"):
        desktop.click(10, 10)
    assert not any(event[0] == "button" for event in backend.events)


def test_explicit_focus_is_only_way_to_change_target():
    desktop, backend = locked_desktop()
    desktop.focus_window(20)
    summary = desktop.target_summary()
    assert summary["pid"] == 200
    assert summary["window_id"] == 20
    desktop.click(100, 100)


def test_type_text_rechecks_target_between_characters():
    desktop, backend = locked_desktop()
    original = backend.unicode_text

    def switch_after_first(text):
        original(text)
        if text == "a":
            backend.front_pid = 200
            backend.focused = {"window_id": 20, "title": "Chat", "modal": False}

    backend.unicode_text = switch_after_first
    with pytest.raises(DesktopError, match="locked"):
        desktop.type_text("ab")
    assert ("text", "a") in backend.events
    assert ("text", "b") not in backend.events


def test_drag_releases_mouse_even_when_pause_interrupts():
    backend = FakeBackend()

    def check():
        down = any(event[:5] == ("button", 10, 10, "left", True) for event in backend.events)
        moved_after_down = down and sum(event[0] == "move" for event in backend.events) >= 2
        if moved_after_down:
            raise PermissionError("Paused")

    desktop = Desktop(check, backend=backend)
    desktop.focus_window(10)
    with pytest.raises(PermissionError):
        desktop.drag(10, 10, 100, 100, 0.05)
    assert any(event[0] == "button" and event[4] is False for event in backend.events)


def test_screenshot_coordinate_mapping_uses_quartz_points():
    desktop, backend = locked_desktop()
    _data, meta = desktop.screenshot(region=(0, 0, 200, 100), max_width=100)
    assert meta["coordinate_space"] == "quartz_global_points"
    assert meta["output_width"] == 100
    assert meta["scale_x"] == pytest.approx(0.5)
