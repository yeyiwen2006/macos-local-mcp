"""macOS privacy permission checks.

Permission prompts are local-operator actions. MCP tools only report current state.
"""
from __future__ import annotations

import json
import sys


class PermissionUnavailable(RuntimeError):
    pass


def _quartz():
    if sys.platform != "darwin":
        raise PermissionUnavailable("macOS is required")
    import Quartz
    return Quartz


def _application_services():
    if sys.platform != "darwin":
        raise PermissionUnavailable("macOS is required")
    import ApplicationServices
    return ApplicationServices


def accessibility_trusted(*, prompt: bool = False) -> bool:
    ax = _application_services()
    if prompt and hasattr(ax, "AXIsProcessTrustedWithOptions"):
        option = getattr(ax, "kAXTrustedCheckOptionPrompt", "AXTrustedCheckOptionPrompt")
        return bool(ax.AXIsProcessTrustedWithOptions({option: True}))
    return bool(ax.AXIsProcessTrusted())


def screen_recording_allowed(*, request: bool = False) -> bool:
    q = _quartz()
    if hasattr(q, "CGPreflightScreenCaptureAccess") and q.CGPreflightScreenCaptureAccess():
        return True
    if request and hasattr(q, "CGRequestScreenCaptureAccess"):
        return bool(q.CGRequestScreenCaptureAccess())
    return False


def permission_status() -> dict:
    if sys.platform != "darwin":
        return {
            "platform": sys.platform,
            "accessibility": False,
            "screen_recording": False,
            "ready_for_desktop_input": False,
            "ready_for_screenshot": False,
        }
    accessibility = accessibility_trusted()
    screen = screen_recording_allowed()
    return {
        "platform": "darwin",
        "accessibility": accessibility,
        "screen_recording": screen,
        "ready_for_desktop_input": accessibility,
        "ready_for_screenshot": screen,
    }


def main() -> None:
    request = "--request" in sys.argv
    if request and sys.platform == "darwin":
        # These calls may show system UI. They are intentionally only reachable
        # from a local command, never from a remote MCP tool.
        accessibility_trusted(prompt=True)
        screen_recording_allowed(request=True)
    print(json.dumps(permission_status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
