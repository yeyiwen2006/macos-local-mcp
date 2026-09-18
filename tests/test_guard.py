from __future__ import annotations

import json

import pytest

from macos_local_mcp.guard import Guard


def test_pause_and_resume_marker_behavior(tmp_path):
    guard = Guard(tmp_path / "state")
    assert guard.status()["paused"] is False
    guard.pause()
    assert guard.status()["paused"] is True
    with pytest.raises(PermissionError):
        guard.check()
    guard.paused_file.unlink()
    guard.check()


def test_audit_excludes_tool_contents_when_caller_uses_metadata_only(tmp_path):
    guard = Guard(tmp_path / "state")
    with guard.action("write_file", {"path": "/tmp/demo", "input_characters": 5}):
        pass
    files = list((guard.state / "audit").glob("*.jsonl"))
    text = files[0].read_text(encoding="utf-8")
    assert "write_file" in text
    assert "secret body" not in text


def test_nonempty_unmarked_state_directory_is_rejected(tmp_path):
    state = tmp_path / "foreign"
    state.mkdir()
    (state / "file.txt").write_text("x")
    with pytest.raises(ValueError, match="non-service"):
        Guard(state)
