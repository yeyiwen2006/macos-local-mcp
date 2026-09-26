from __future__ import annotations

import os
from pathlib import Path

import pytest

from macos_local_mcp.files import Files
from macos_local_mcp.guard import Guard


def make_files(tmp_path):
    state = tmp_path / "state"
    guard = Guard(state)
    return guard, Files(guard)


def test_text_write_read_backup_and_conflict(tmp_path):
    guard, files = make_files(tmp_path)
    p = tmp_path / "中文.txt"
    created = files.write(str(p), "你好🙂")
    assert created["backup_path"] is None
    assert files.read_text(str(p))["text"] == "你好🙂"

    # Fast consecutive writes can share an mtime on portable test filesystems.
    os.utime(p, ns=(1_000_000_000, 1_000_000_000))
    before = files.info(str(p))["modified_ns"]
    replaced = files.write(str(p), "替换", overwrite=True, expected_modified_ns=before)
    assert Path(replaced["backup_path"]).read_bytes() == "你好🙂".encode()
    assert p.read_text(encoding="utf-8") == "替换"

    with pytest.raises(ValueError, match="changed"):
        files.write(str(p), "no", overwrite=True, expected_modified_ns=before)


def test_binary_pagination(tmp_path):
    _guard, files = make_files(tmp_path)
    p = tmp_path / "data.bin"
    p.write_bytes(b"abcdef")
    first = files.read_binary(str(p), offset=0, length=3)
    assert first["bytes"] == 3
    assert first["next_offset"] == 3
    second = files.read_binary(str(p), offset=3, length=3)
    assert second["next_offset"] is None


def test_service_state_and_source_are_hidden_from_file_tools(tmp_path, monkeypatch):
    guard, files = make_files(tmp_path)
    with pytest.raises(PermissionError):
        files.info(str(guard.state))
    with pytest.raises(PermissionError):
        files.mkdir(str(guard.state / "x"))


def test_symlink_mutation_is_rejected(tmp_path):
    _guard, files = make_files(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("x")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="symlink"):
        files.write(str(link), "y", overwrite=True)


def test_extended_attributes_are_rejected_when_present(tmp_path, monkeypatch):
    _guard, files = make_files(tmp_path)
    p = tmp_path / "x.txt"
    p.write_text("x")
    import macos_local_mcp.files as files_module
    monkeypatch.setattr(files_module.os, "listxattr", lambda _p: ["com.example"], raising=False)
    with pytest.raises(ValueError, match="extended attributes"):
        files.write(str(p), "y", overwrite=True)


def test_recycle_failure_never_deletes_original(tmp_path, monkeypatch):
    _guard, files = make_files(tmp_path)
    p = tmp_path / "keep.txt"
    p.write_text("keep")

    def fail(_path):
        raise OSError("trash unavailable")

    monkeypatch.setattr("send2trash.send2trash", fail)
    with pytest.raises(OSError):
        files.recycle(str(p))
    assert p.exists()
