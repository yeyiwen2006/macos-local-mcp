"""macOS desktop control with explicit target locking.

The native backend is loaded only on macOS. The controller itself is backend-driven,
which lets safety semantics be tested on non-macOS CI without sending real input.
"""
from __future__ import annotations

import io
import math
import sys
import threading
import time
from typing import Callable



class DesktopError(RuntimeError):
    """Desktop control is unavailable or a safety check rejected the operation."""


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} through {maximum}.")
    return value


def _duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("duration must be a finite number from 0.05 through 5 seconds.")
    result = float(value)
    if not math.isfinite(result) or not 0.05 <= result <= 5.0:
        raise ValueError("duration must be a finite number from 0.05 through 5 seconds.")
    return result


def _region(region: object, bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if region is None:
        return bounds
    if not isinstance(region, (tuple, list)) or len(region) != 4:
        raise ValueError("region must contain left, top, right, bottom.")
    left, top, right, bottom = (
        _integer(value, "region coordinate", -(2**31), 2**31 - 1) for value in region
    )
    if not (bounds[0] <= left < right <= bounds[2] and bounds[1] <= top < bottom <= bounds[3]):
        raise ValueError("region must be a positive rectangle inside the virtual desktop.")
    return left, top, right, bottom


def _point(x: object, y: object, monitors: list[dict]) -> tuple[int, int]:
    x = _integer(x, "x", -(2**31), 2**31 - 1)
    y = _integer(y, "y", -(2**31), 2**31 - 1)
    if not any(m["left"] <= x < m["right"] and m["top"] <= y < m["bottom"] for m in monitors):
        raise ValueError("Coordinates must lie on a connected monitor.")
    return x, y


_KEYCODES = {
    "ctrl": 59,
    "shift": 56,
    "alt": 58,
    "option": 58,
    "command": 55,
    "cmd": 55,
    "enter": 36,
    "tab": 48,
    "escape": 53,
    "space": 49,
    "backspace": 51,
    "delete": 117,
    "home": 115,
    "end": 119,
    "pageup": 116,
    "pagedown": 121,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "=": 24,
    "9": 25,
    "7": 26,
    "-": 27,
    "8": 28,
    "0": 29,
    "]": 30,
    "o": 31,
    "u": 32,
    "[": 33,
    "i": 34,
    "p": 35,
    "l": 37,
    "j": 38,
    "'": 39,
    "k": 40,
    ";": 41,
    "\\": 42,
    ",": 43,
    "/": 44,
    "n": 45,
    "m": 46,
    ".": 47,
}
_MODIFIERS = {"ctrl", "shift", "alt", "option", "command", "cmd"}


def _chord(keys: object) -> list[tuple[str, int, bool]]:
    if not isinstance(keys, list) or not 1 <= len(keys) <= 5:
        raise ValueError("keys must be a list containing 1 to 5 key names.")
    result = []
    seen = set()
    for raw in keys:
        if not isinstance(raw, str) or len(raw) > 16:
            raise ValueError("Every key must be a supported key name.")
        name = raw.lower()
        aliases = {"control": "ctrl", "return": "enter", "esc": "escape", "pgup": "pageup",
                   "pgdn": "pagedown", "del": "delete", "super": "command", "win": "command"}
        name = aliases.get(name, name)
        if name not in _KEYCODES:
            raise ValueError(f"Unsupported key: {raw!r}; use type_text for characters.")
        canonical = "alt" if name == "option" else "command" if name == "cmd" else name
        if canonical in seen:
            raise ValueError("A chord cannot contain duplicate keys.")
        seen.add(canonical)
        result.append((canonical, _KEYCODES[name], canonical in _MODIFIERS))
    if sum(not item[2] for item in result) > 1:
        raise ValueError("A chord may contain modifiers and at most one ordinary key.")
    return sorted(result, key=lambda item: not item[2])


class _NativeBackend:
    def __init__(self):
        if sys.platform != "darwin":
            raise DesktopError("Desktop control requires macOS.")
        import AppKit
        import Quartz
        import ApplicationServices
        self.AppKit = AppKit
        self.Quartz = Quartz
        self.AX = ApplicationServices

    def permission_status(self) -> dict:
        from .permissions import permission_status
        return permission_status()

    def _require_accessibility(self) -> None:
        if not bool(self.AX.AXIsProcessTrusted()):
            raise DesktopError(
                "Accessibility permission is required. Grant it locally in System Settings > "
                "Privacy & Security > Accessibility, then restart the service."
            )

    def _require_screen_recording(self) -> None:
        q = self.Quartz
        if hasattr(q, "CGPreflightScreenCaptureAccess") and not q.CGPreflightScreenCaptureAccess():
            raise DesktopError(
                "Screen Recording permission is required. Grant it locally in System Settings > "
                "Privacy & Security > Screen Recording, then restart the service."
            )

    def monitors(self) -> list[dict]:
        screens = list(self.AppKit.NSScreen.screens())
        if not screens:
            raise DesktopError("No active macOS displays were found.")
        main = self.AppKit.NSScreen.mainScreen() or screens[0]
        main_frame = main.frame()
        main_height = float(main_frame.size.height)
        result = []
        for index, screen in enumerate(screens):
            frame = screen.frame()
            left = round(float(frame.origin.x))
            width = round(float(frame.size.width))
            height = round(float(frame.size.height))
            top = round(main_height - float(frame.origin.y) - float(frame.size.height))
            desc = screen.deviceDescription() or {}
            result.append({
                "device": str(desc.get("NSScreenNumber", index)),
                "left": left,
                "top": top,
                "right": left + width,
                "bottom": top + height,
                "width": width,
                "height": height,
                "primary": screen == main,
                "coordinate_unit": "Quartz global points",
            })
        return result

    def bounds(self) -> tuple[int, int, int, int]:
        monitors = self.monitors()
        return (
            min(m["left"] for m in monitors),
            min(m["top"] for m in monitors),
            max(m["right"] for m in monitors),
            max(m["bottom"] for m in monitors),
        )

    def windows(self) -> list[dict]:
        q = self.Quartz
        options = q.kCGWindowListOptionOnScreenOnly | q.kCGWindowListExcludeDesktopElements
        raw = q.CGWindowListCopyWindowInfo(options, q.kCGNullWindowID) or []
        result = []
        front_pid = self.frontmost_pid()
        front_window_assigned = False
        for item in raw:
            try:
                layer = int(item.get(q.kCGWindowLayer, 0))
                bounds = item.get(q.kCGWindowBounds) or {}
                width = int(round(float(bounds.get("Width", 0))))
                height = int(round(float(bounds.get("Height", 0))))
                if layer != 0 or width <= 1 or height <= 1:
                    continue
                window_id = int(item[q.kCGWindowNumber])
                pid = int(item[q.kCGWindowOwnerPID])
                is_foreground = pid == front_pid and not front_window_assigned
                if is_foreground:
                    front_window_assigned = True
                result.append({
                    "hwnd": window_id,
                    "window_id": window_id,
                    "title": str(item.get(q.kCGWindowName) or ""),
                    "owner": str(item.get(q.kCGWindowOwnerName) or ""),
                    "pid": pid,
                    "left": int(round(float(bounds.get("X", 0)))),
                    "top": int(round(float(bounds.get("Y", 0)))),
                    "right": int(round(float(bounds.get("X", 0)))) + width,
                    "bottom": int(round(float(bounds.get("Y", 0)))) + height,
                    "foreground": is_foreground,
                })
            except (KeyError, TypeError, ValueError):
                continue
        return result[:256]

    def window_record(self, window_id: int) -> dict:
        for item in self.windows():
            if item["window_id"] == window_id:
                return item
        raise DesktopError("Window disappeared or is no longer visible.")

    def frontmost_pid(self) -> int:
        app = self.AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app else 0

    def frontmost_window_id(self) -> int:
        """Return the topmost normal window for the frontmost app without Accessibility."""
        pid = self.frontmost_pid()
        if not pid:
            return 0
        for window in self.windows():
            if window["pid"] == pid and window.get("foreground"):
                return int(window["window_id"])
        return 0

    def process_identity(self, pid: int) -> dict:
        import psutil
        try:
            process = psutil.Process(pid)
            create_time = float(process.create_time())
            executable = process.exe()
        except (psutil.Error, OSError) as exc:
            raise DesktopError("Cannot verify the target process identity.") from exc
        running = self.AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bundle_id = str(running.bundleIdentifier() or "") if running else ""
        return {
            "pid": int(pid),
            "create_time": create_time,
            "executable": executable,
            "bundle_id": bundle_id,
        }

    def _ax_value(self, element, attribute):
        ax = self.AX
        try:
            result = ax.AXUIElementCopyAttributeValue(element, attribute, None)
        except Exception:
            return None
        if isinstance(result, tuple) and len(result) == 2:
            error, value = result
            if int(error) == 0:
                return value
            return None
        return result

    def _ax_window_id(self, element) -> int:
        ax = self.AX
        number = self._ax_value(
            element, getattr(ax, "kAXWindowNumberAttribute", "AXWindowNumber")
        )
        try:
            return int(number or 0)
        except (TypeError, ValueError):
            return 0

    def focused_window_signature(self, pid: int) -> dict | None:
        self._require_accessibility()
        ax = self.AX
        app = ax.AXUIElementCreateApplication(pid)
        focused = self._ax_value(app, ax.kAXFocusedWindowAttribute)
        if focused is None:
            return None
        title = self._ax_value(focused, ax.kAXTitleAttribute)
        modal = self._ax_value(focused, getattr(ax, "kAXModalAttribute", "AXModal"))
        title_text = str(title or "")
        window_id = self._ax_window_id(focused)
        candidates = [w for w in self.windows() if w["pid"] == pid]
        chosen = None
        if window_id:
            chosen = next((w for w in candidates if w["window_id"] == window_id), None)
        if chosen is None and title_text:
            chosen = next((w for w in candidates if w["title"] == title_text), None)
        if chosen is None and candidates:
            chosen = candidates[0]
        return {
            "window_id": window_id or (chosen["window_id"] if chosen else 0),
            "title": title_text or (chosen["title"] if chosen else ""),
            "modal": bool(modal),
        }

    def focus_window(self, window_id: int) -> dict:
        self._require_accessibility()
        record = self.window_record(window_id)
        pid = record["pid"]
        app = self.AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            raise DesktopError("Target application is no longer running.")
        options = getattr(self.AppKit, "NSApplicationActivateIgnoringOtherApps", 1 << 1)
        app.activateWithOptions_(options)

        ax = self.AX
        ax_app = ax.AXUIElementCreateApplication(pid)
        windows = self._ax_value(ax_app, ax.kAXWindowsAttribute) or []
        target_title = record.get("title") or ""
        candidate = None
        for ax_window in windows:
            if self._ax_window_id(ax_window) == window_id:
                candidate = ax_window
                break
        if candidate is None and target_title:
            for ax_window in windows:
                title = self._ax_value(ax_window, ax.kAXTitleAttribute)
                if str(title or "") == target_title:
                    candidate = ax_window
                    break
        if candidate is None and len(windows) == 1:
            candidate = windows[0]
        if candidate is None:
            raise DesktopError(
                "Could not map the selected Quartz window to a unique Accessibility window."
            )
        if candidate is not None:
            try:
                ax.AXUIElementPerformAction(candidate, ax.kAXRaiseAction)
            except Exception:
                pass
            try:
                ax.AXUIElementSetAttributeValue(candidate, ax.kAXMainAttribute, True)
            except Exception:
                pass

        deadline = time.monotonic() + 1.0
        while self.frontmost_pid() != pid:
            if time.monotonic() >= deadline:
                raise DesktopError("macOS refused to activate the target application.")
            time.sleep(0.025)
        return self.window_record(window_id)

    def capture_png(self, bbox: tuple[int, int, int, int]) -> bytes:
        self._require_screen_recording()
        q, a = self.Quartz, self.AppKit
        left, top, right, bottom = bbox
        rect = q.CGRectMake(left, top, right - left, bottom - top)
        image = q.CGWindowListCreateImage(
            rect,
            q.kCGWindowListOptionOnScreenOnly,
            q.kCGNullWindowID,
            q.kCGWindowImageDefault,
        )
        if image is None:
            raise DesktopError("macOS screen capture returned no image.")
        rep = a.NSBitmapImageRep.alloc().initWithCGImage_(image)
        png_type = getattr(a, "NSBitmapImageFileTypePNG", getattr(a, "NSPNGFileType", None))
        data = rep.representationUsingType_properties_(png_type, {})
        if data is None:
            raise DesktopError("Could not encode the macOS screenshot.")
        return bytes(data)

    def _post(self, event) -> None:
        self.Quartz.CGEventPost(self.Quartz.kCGHIDEventTap, event)

    def mouse_move(self, x: int, y: int) -> None:
        q = self.Quartz
        event = q.CGEventCreateMouseEvent(None, q.kCGEventMouseMoved, (x, y), q.kCGMouseButtonLeft)
        self._post(event)

    def mouse_button(self, x: int, y: int, button: str, down: bool) -> None:
        q = self.Quartz
        mapping = {
            "left": (q.kCGMouseButtonLeft, q.kCGEventLeftMouseDown, q.kCGEventLeftMouseUp),
            "right": (q.kCGMouseButtonRight, q.kCGEventRightMouseDown, q.kCGEventRightMouseUp),
            "middle": (q.kCGMouseButtonCenter, q.kCGEventOtherMouseDown, q.kCGEventOtherMouseUp),
        }
        mouse_button, down_type, up_type = mapping[button]
        event = q.CGEventCreateMouseEvent(None, down_type if down else up_type, (x, y), mouse_button)
        self._post(event)

    def scroll(self, vertical: int, horizontal: int) -> None:
        q = self.Quartz
        event = q.CGEventCreateScrollWheelEvent(
            None, q.kCGScrollEventUnitLine, 2, int(vertical), int(horizontal)
        )
        self._post(event)

    def held_inputs(self) -> list[str]:
        q = self.Quartz
        source = q.kCGEventSourceStateCombinedSessionState
        keys = [
            (56, "Left Shift"), (60, "Right Shift"),
            (59, "Left Control"), (62, "Right Control"),
            (58, "Left Option"), (61, "Right Option"),
            (55, "Left Command"), (54, "Right Command"),
        ]
        buttons = [(0, "Left mouse button"), (1, "Right mouse button"), (2, "Middle mouse button")]
        try:
            held = [
                label for keycode, label in keys
                if q.CGEventSourceKeyState(source, keycode)
            ]
            held.extend(
                label for button, label in buttons
                if q.CGEventSourceButtonState(source, button)
            )
            return held
        except Exception as exc:
            raise DesktopError("Could not verify the current keyboard/mouse input state.") from exc

    def key(self, keycode: int, down: bool, modifiers: tuple[str, ...] = ()) -> None:
        q = self.Quartz
        event = q.CGEventCreateKeyboardEvent(None, keycode, bool(down))
        flag_map = {
            "shift": q.kCGEventFlagMaskShift,
            "ctrl": q.kCGEventFlagMaskControl,
            "alt": q.kCGEventFlagMaskAlternate,
            "command": q.kCGEventFlagMaskCommand,
        }
        flags = 0
        for modifier in modifiers:
            flags |= int(flag_map[modifier])
        q.CGEventSetFlags(event, flags)
        self._post(event)

    def unicode_text(self, text: str) -> None:
        q = self.Quartz
        raw = text.encode("utf-16-le")
        units = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]
        down = q.CGEventCreateKeyboardEvent(None, 0, True)
        up = q.CGEventCreateKeyboardEvent(None, 0, False)
        q.CGEventKeyboardSetUnicodeString(down, len(units), units)
        q.CGEventKeyboardSetUnicodeString(up, len(units), units)
        self._post(down)
        self._post(up)


class Desktop:
    def __init__(self, check: Callable[[], None], backend=None):
        if not callable(check):
            raise TypeError("check must be callable.")
        self._check = check
        self._backend = backend if backend is not None else _NativeBackend()
        self._lock = threading.RLock()
        self.input_target: dict | None = None
        self.expected_foreground_hwnd: int | None = None

    def _checkpoint(self) -> None:
        self._check()

    def permission_status(self) -> dict:
        return self._backend.permission_status()

    def monitors(self) -> list[dict]:
        with self._lock:
            self._checkpoint()
            return self._backend.monitors()

    def _bounds(self) -> tuple[int, int, int, int]:
        return self._backend.bounds()

    def windows(self) -> list[dict]:
        with self._lock:
            self._checkpoint()
            return self._backend.windows()

    def foreground_window(self) -> int:
        return int(self._backend.frontmost_window_id())

    def _target_summary(self) -> dict | None:
        if not self.input_target:
            return None
        return {
            "hwnd": self.input_target["window_id"],
            "window_id": self.input_target["window_id"],
            "pid": self.input_target["pid"],
            "title": self.input_target["title"],
            "bundle_id": self.input_target.get("bundle_id", ""),
        }

    def target_summary(self) -> dict | None:
        with self._lock:
            return self._target_summary()

    def focus_window(self, hwnd: int) -> dict:
        _integer(hwnd, "hwnd", 1, 2**32 - 1)
        with self._lock:
            self._checkpoint()
            record = self._backend.focus_window(hwnd)
            identity = self._backend.process_identity(record["pid"])
            signature = self._backend.focused_window_signature(record["pid"]) or {}
            actual_id = int(signature.get("window_id") or record["window_id"])
            self.input_target = {
                "window_id": actual_id,
                "pid": record["pid"],
                "title": signature.get("title") or record.get("title") or "",
                **identity,
            }
            return {**record, "input_target_locked": True}

    def _process_matches(self, target: dict) -> bool:
        try:
            identity = self._backend.process_identity(target["pid"])
        except DesktopError:
            return False
        return (
            identity["pid"] == target["pid"]
            and abs(identity["create_time"] - target["create_time"]) < 0.001
            and identity["executable"] == target["executable"]
            and identity.get("bundle_id", "") == target.get("bundle_id", "")
        )

    def _target_matches(self, *, verify_process: bool = False) -> bool:
        target = self.input_target
        if not target:
            return False
        if self._backend.frontmost_pid() != target["pid"]:
            return False
        if verify_process and not self._process_matches(target):
            return False
        signature = self._backend.focused_window_signature(target["pid"])
        if not signature:
            return False
        return bool(
            signature.get("window_id") == target["window_id"]
            or signature.get("modal") is True
        )

    def _assert_input_target(self, *, verify_process: bool = False) -> None:
        if not self.input_target:
            raise DesktopError(
                "No desktop input target is locked. Call desktop_windows, then desktop_focus_window "
                "before sending mouse or keyboard input."
            )
        if not self._target_matches(verify_process=verify_process):
            title = self.input_target.get("title") or "(untitled window)"
            raise DesktopError(
                f"Desktop input is locked to {title!r} (PID {self.input_target['pid']}). "
                "The foreground application/window no longer matches the explicit target. "
                "Screenshots never retarget input; return to the target or explicitly call "
                "desktop_focus_window to choose a new one."
            )

    def validate_input_target(self, hwnd: int) -> dict:
        with self._lock:
            current = self.foreground_window()
            if current != hwnd:
                raise DesktopError("Foreground window changed since the screenshot; take a fresh screenshot.")
            self._assert_input_target(verify_process=True)
            return self._target_summary() or {}

    def screenshot(self, region: tuple[int, int, int, int] | None = None,
                   max_width: int = 1600) -> tuple[bytes, dict]:
        _integer(max_width, "max_width", 64, 3840)
        with self._lock:
            self._checkpoint()
            bbox = _region(region, self._bounds())
            foreground_pid = self._backend.frontmost_pid()
            foreground = self.foreground_window()
            data = self._backend.capture_png(bbox)
            self._checkpoint()
            if self._backend.frontmost_pid() != foreground_pid or self.foreground_window() != foreground:
                raise DesktopError("Foreground focus changed during capture; take a fresh screenshot.")

            from PIL import Image
            image = Image.open(io.BytesIO(data))
            try:
                width_points = bbox[2] - bbox[0]
                height_points = bbox[3] - bbox[1]
                scale = min(1.0, max_width / image.width, math.sqrt(4_000_000 / (image.width * image.height)))
                out_size = max(1, round(image.width * scale)), max(1, round(image.height * scale))
                if out_size != image.size:
                    resized = image.resize(out_size, Image.Resampling.LANCZOS)
                else:
                    resized = image.copy()
                try:
                    output = io.BytesIO()
                    resized.save(output, format="PNG")
                    out_width, out_height = resized.size
                finally:
                    resized.close()
            finally:
                image.close()

            return output.getvalue(), {
                "left": bbox[0],
                "top": bbox[1],
                "native_width": width_points,
                "native_height": height_points,
                "output_width": out_width,
                "output_height": out_height,
                "scale_x": out_width / width_points,
                "scale_y": out_height / height_points,
                "foreground_hwnd": foreground,
                "foreground_pid": foreground_pid,
                "input_target": self._target_summary(),
                "input_allowed": self._snapshot_input_allowed(),
                "coordinate_space": "quartz_global_points",
                "coordinate_mapping": "x = left + image_x / scale_x; y = top + image_y / scale_y",
            }

    def _snapshot_input_allowed(self) -> bool:
        try:
            return self._target_matches(verify_process=True)
        except DesktopError:
            return False

    def _before_input(self) -> None:
        self._checkpoint()
        self._assert_input_target(verify_process=True)

    def _wait_for_released_inputs(self) -> None:
        deadline = time.monotonic() + 1.0
        idle_since = None
        last_held: list[str] = []
        while True:
            self._before_input()
            held = self._backend.held_inputs()
            now = time.monotonic()
            if held:
                last_held = held
                idle_since = None
            elif idle_since is None:
                idle_since = now
            elif now - idle_since >= 0.1:
                return
            if now >= deadline:
                names = ", ".join(held or last_held) or "an unsettled modifier/button state"
                raise DesktopError(
                    f"Input did not become idle within 1 second. Last detected held input: {names}. "
                    "Release it locally, take a fresh screenshot, then retry. No input was sent."
                )
            time.sleep(min(0.02, deadline - now))

    def _prepare_input(self) -> None:
        self._before_input()
        self._wait_for_released_inputs()
        self._before_input()

    def move(self, x: int, y: int) -> dict:
        with self._lock:
            x, y = _point(x, y, self._backend.monitors())
            self._prepare_input()
            self._backend.mouse_move(x, y)
            return {"x": x, "y": y}

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
        if button not in ("left", "right", "middle"):
            raise ValueError("button must be left, right, or middle.")
        _integer(clicks, "clicks", 1, 3)
        with self._lock:
            x, y = _point(x, y, self._backend.monitors())
            self._prepare_input()
            self._backend.mouse_move(x, y)
            for index in range(clicks):
                self._before_input()
                self._backend.mouse_button(x, y, button, True)
                try:
                    self._checkpoint()
                finally:
                    self._backend.mouse_button(x, y, button, False)
                if index + 1 < clicks:
                    time.sleep(0.08)
            return {"x": x, "y": y, "button": button, "clicks": clicks}

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> dict:
        duration = _duration(duration)
        with self._lock:
            monitors = self._backend.monitors()
            _point(x1, y1, monitors)
            _point(x2, y2, monitors)
            self._prepare_input()
            self._backend.mouse_move(x1, y1)
            self._before_input()
            self._backend.mouse_button(x1, y1, "left", True)
            current_x, current_y = x1, y1
            try:
                steps = max(2, math.ceil(duration * 40))
                start = time.monotonic()
                for index in range(1, steps + 1):
                    self._before_input()
                    x = round(x1 + (x2 - x1) * index / steps)
                    y = round(y1 + (y2 - y1) * index / steps)
                    _point(x, y, monitors)
                    remaining = start + duration * index / steps - time.monotonic()
                    if remaining > 0:
                        time.sleep(min(remaining, 0.05))
                    self._backend.mouse_move(x, y)
                    current_x, current_y = x, y
            finally:
                self._backend.mouse_button(current_x, current_y, "left", False)
            return {"from": [x1, y1], "to": [x2, y2], "duration": duration}

    def scroll(self, x: int, y: int, vertical: int = 0, horizontal: int = 0) -> dict:
        _integer(vertical, "vertical", -100, 100)
        _integer(horizontal, "horizontal", -100, 100)
        if vertical == 0 and horizontal == 0:
            raise ValueError("At least one scroll direction must be nonzero.")
        with self._lock:
            x, y = _point(x, y, self._backend.monitors())
            self._prepare_input()
            self._backend.mouse_move(x, y)
            self._before_input()
            self._backend.scroll(vertical, horizontal)
            return {"x": x, "y": y, "vertical": vertical, "horizontal": horizontal,
                    "units": "line notches; positive means up/right"}

    def keypress(self, keys: list[str]) -> dict:
        chord = _chord(keys)
        with self._lock:
            self._prepare_input()
            pressed: list[tuple[str, int, bool]] = []
            active_modifiers: list[str] = []
            try:
                for name, keycode, modifier in chord:
                    self._before_input()
                    if modifier:
                        active_modifiers.append(name)
                    pressed.append((name, keycode, modifier))
                    self._backend.key(keycode, True, tuple(active_modifiers))
            finally:
                for name, keycode, modifier in reversed(pressed):
                    try:
                        if modifier and name in active_modifiers:
                            active_modifiers.remove(name)
                        self._backend.key(keycode, False, tuple(active_modifiers))
                    except Exception:
                        pass
            return {"keys": [name for name, _keycode, _modifier in chord]}

    def type_text(self, text: str) -> dict:
        if not isinstance(text, str) or not 1 <= len(text) <= 4000:
            raise ValueError("text must contain 1 to 4000 Unicode characters.")
        if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text) or "\x7f" in text:
            raise ValueError("text contains unsupported control characters.")
        with self._lock:
            self._prepare_input()
            deadline = time.monotonic() + 20
            for index, char in enumerate(text):
                if time.monotonic() > deadline:
                    raise DesktopError(f"Text entry stopped after {index} characters because the 20 second limit elapsed.")
                self._before_input()
                if char == "\n" or char == "\r":
                    self._backend.key(_KEYCODES["enter"], True)
                    self._backend.key(_KEYCODES["enter"], False)
                elif char == "\t":
                    self._backend.key(_KEYCODES["tab"], True)
                    self._backend.key(_KEYCODES["tab"], False)
                else:
                    self._backend.unicode_text(char)
            return {"characters": len(text), "clipboard_used": False}
