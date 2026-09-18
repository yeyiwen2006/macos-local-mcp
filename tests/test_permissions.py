import sys

from macos_local_mcp.permissions import permission_status


def test_permission_status_is_nonprompting_and_portable():
    status = permission_status()
    assert "accessibility" in status
    assert "screen_recording" in status
    assert "ready_for_desktop_input" in status
    if sys.platform != "darwin":
        assert status["accessibility"] is False
        assert status["screen_recording"] is False
