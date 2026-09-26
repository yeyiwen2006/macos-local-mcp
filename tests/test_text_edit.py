from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from macos_local_mcp.files import Files
from macos_local_mcp.guard import Guard
from macos_local_mcp.server import build_server


@pytest.fixture
def files(tmp_path):
    return Files(Guard(tmp_path / "state"))


@pytest.mark.parametrize("encoding,data,old,new,expected", [
    ("utf-8-sig", b"\xef\xbb\xbf" + "首行\r\n旧值🙂\r\n末行\n".encode(), "旧值", "新值",
     b"\xef\xbb\xbf" + "首行\r\n新值🙂\r\n末行\n".encode()),
    ("utf-8-sig", b"start\r\nold\nend\r", "old", "new\r\nmore", b"start\r\nnew\r\nmore\nend\r"),
    ("utf-16", b"\xff\xfe" + "首\r\n旧🙂尾".encode("utf-16-le"), "旧", "新",
     b"\xff\xfe" + "首\r\n新🙂尾".encode("utf-16-le")),
    ("utf-16", b"\xfe\xff" + "首\n旧🙂尾".encode("utf-16-be"), "旧", "新",
     b"\xfe\xff" + "首\n新🙂尾".encode("utf-16-be")),
    ("gb18030", "首行\r\n旧值🙂尾\n".encode("gb18030"), "旧值", "新值",
     "首行\r\n新值🙂尾\n".encode("gb18030")),
])
def test_exact_edit_preserves_encoding_bytes_and_backup(files, tmp_path, encoding, data, old, new, expected):
    path = tmp_path / "中文.txt"
    path.write_bytes(data)
    read = files.read_text(str(path), encoding=encoding)
    assert read["version"] == files.info(str(path))["version"]
    result = files.edit_text(str(path), old, new, read["version"], encoding)
    assert path.read_bytes() == expected
    assert Path(result["backup_path"]).read_bytes() == data
    assert result["changed"] is True and result["replacements"] == 1
    assert result["version"] == files.info(str(path))["version"]
    assert result["version"] != read["version"]


@pytest.mark.parametrize("data,old", [("aaaa", "aa"), ("aba aba", "aba"), ("abc", "missing"), ("abc", "")])
def test_absent_ambiguous_and_empty_matches_leave_original(files, tmp_path, data, old):
    path = tmp_path / "sample.txt"
    path.write_text(data, encoding="utf-8")
    with pytest.raises(ValueError):
        files.edit_text(str(path), old, "replacement", files.info(str(path))["version"])
    assert path.read_text(encoding="utf-8") == data
    assert not (files.guard.state / "backups").exists()


def test_noop_does_not_replace_or_backup(files, tmp_path):
    path = tmp_path / "unchanged.txt"
    path.write_bytes(b"one\r\ntwo")
    version = files.info(str(path))["version"]
    result = files.edit_text(str(path), "one", "one", version)
    assert result["changed"] is False and result["replacements"] == 0
    assert result["backup_path"] is None
    assert files.info(str(path))["version"] == version


def test_explicit_utf8_cannot_remove_original_bom(files, tmp_path):
    path = tmp_path / "bom.txt"
    original = b"\xef\xbb\xbfold"
    path.write_bytes(original)
    with pytest.raises(ValueError, match="byte-order mark"):
        files.edit_text(str(path), "\ufeffold", "new", files.info(str(path))["version"], "utf-8")
    assert path.read_bytes() == original


def test_stale_version_after_same_size_replacement_is_rejected(files, tmp_path):
    path = tmp_path / "changed.txt"
    path.write_bytes(b"old")
    read = files.read_text(str(path))
    modified = path.stat().st_mtime_ns
    replacement = tmp_path / "replacement.txt"
    replacement.write_bytes(b"new")
    os.utime(replacement, ns=(modified, modified))
    os.replace(replacement, path)
    with pytest.raises(ValueError, match="changed"):
        files.edit_text(str(path), "old", "bad", read["version"])
    assert path.read_bytes() == b"new"


def test_change_during_backup_is_not_overwritten(files, tmp_path, monkeypatch):
    path = tmp_path / "changed.txt"
    path.write_bytes(b"old")
    original_backup = files.backup
    def backup_then_change(p):
        saved = original_backup(p)
        p.write_bytes(b"external")
        return saved
    monkeypatch.setattr(files, "backup", backup_then_change)
    with pytest.raises(ValueError, match="changed"):
        files.edit_text(str(path), "old", "new", files.info(str(path))["version"])
    assert path.read_bytes() == b"external"
    assert not list(tmp_path.glob(".mcp-*.tmp"))


def test_change_between_read_and_commit_is_rejected(files, tmp_path, monkeypatch):
    path = tmp_path / "changed.txt"
    path.write_bytes(b"old")
    original_write = files._write_bytes
    def change_then_write(*args, **kwargs):
        path.write_bytes(b"external")
        return original_write(*args, **kwargs)
    monkeypatch.setattr(files, "_write_bytes", change_then_write)
    with pytest.raises(ValueError, match="changed"):
        files.edit_text(str(path), "old", "new", files.info(str(path))["version"])
    assert path.read_bytes() == b"external"


def test_read_text_rejects_external_change_instead_of_returning_stale_version(files, tmp_path, monkeypatch):
    path = tmp_path / "changing.txt"
    path.write_bytes(b"first\nsecond\n")
    changed = False
    def replace_during_read():
        nonlocal changed
        if not changed:
            path.write_bytes(b"external")
            changed = True
    monkeypatch.setattr(files.guard, "check", replace_during_read)
    with pytest.raises(ValueError, match="changed"):
        files.read_text(str(path))
    assert path.read_bytes() == b"external"


def test_invalid_encoding_and_size_leave_original(files, tmp_path, monkeypatch):
    import macos_local_mcp.files as module
    path = tmp_path / "data.txt"
    path.write_bytes(b"old")
    version = files.info(str(path))["version"]
    with pytest.raises(ValueError):
        files.edit_text(str(path), "old", "new", version, "latin-1")
    path.write_bytes(b"\xffold")
    with pytest.raises(UnicodeError):
        files.edit_text(str(path), "old", "new", files.info(str(path))["version"])
    path.write_bytes(b"old")
    monkeypatch.setattr(module, "MAX_WRITE", 4)
    with pytest.raises(ValueError, match="limit"):
        files.edit_text(str(path), "old", "too large", files.info(str(path))["version"])
    path.write_bytes(b"oversized")
    with pytest.raises(ValueError, match="limit"):
        files.edit_text(str(path), "oversized", "small", files.info(str(path))["version"])
    assert path.read_bytes() == b"oversized"


def test_edit_is_write_tool_with_required_version_and_pause_guard(files, tmp_path):
    async def scenario():
        server, _ = build_server(files.guard)
        tools = {tool.name: tool for tool in await server.list_tools()}
        edit = tools["edit_text_file"]
        assert edit.annotations.readOnlyHint is False
        assert edit.annotations.destructiveHint is True
        assert "expected_version" in edit.inputSchema["required"]
        path = tmp_path / "sample.txt"
        path.write_bytes(b"old")
        files.guard.pause()
        with pytest.raises(Exception, match="paused"):
            await server.call_tool("edit_text_file", {"path": str(path), "old_text": "old", "new_text": "new",
                                                     "expected_version": files.info(str(path))["version"]})
        assert path.read_bytes() == b"old"
    asyncio.run(scenario())
