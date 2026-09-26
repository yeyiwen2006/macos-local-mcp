from __future__ import annotations

import ctypes
import errno
import getpass
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

import macos_local_mcp.files as module
from macos_local_mcp.files import Files
from macos_local_mcp.guard import Guard


@pytest.fixture
def sample(tmp_path):
    files = Files(Guard(tmp_path / "state"))
    path = tmp_path / "sample.txt"
    path.write_bytes(b"old")
    return files, path


def test_xattr_inspection_error_refuses_overwrite(sample, monkeypatch):
    files, path = sample
    def fail(_path):
        raise OSError("metadata unavailable")
    monkeypatch.setattr(module.os, "listxattr", fail, raising=False)
    with pytest.raises(OSError, match="metadata unavailable"):
        files.write(str(path), "new", overwrite=True)
    assert path.read_bytes() == b"old"


def test_darwin_missing_xattr_api_refuses_overwrite(sample, monkeypatch):
    files, path = sample
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.delattr(module.os, "listxattr", raising=False)
    with pytest.raises(OSError, match="inspection is unavailable"):
        files.write(str(path), "new", overwrite=True)
    assert path.read_bytes() == b"old"


@pytest.mark.parametrize("result,error", [(1, 0), (None, errno.EACCES)])
def test_native_acl_check_presence_or_failure_refuses_overwrite(sample, monkeypatch, result, error):
    files, path = sample
    class Check:
        def __call__(self, fd):
            assert os.fstat(fd).st_size == 3
            ctypes.set_errno(error)
            return result
    class Free:
        def __call__(self, acl):
            assert acl == 1
            return 0
    class Library:
        acl_get_fd = Check()
        acl_free = Free()
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.os, "listxattr", lambda _p: [], raising=False)
    monkeypatch.setattr(module.ctypes, "CDLL", lambda *args, **kwargs: Library())
    with pytest.raises((OSError, ValueError), match="ACL"):
        files.write(str(path), "new", overwrite=True)
    assert path.read_bytes() == b"old"


def test_native_absent_acl_is_distinguished_from_check_failure(sample, monkeypatch):
    _files, path = sample
    class Check:
        def __call__(self, fd):
            assert os.fstat(fd).st_size == 3
            ctypes.set_errno(errno.ENOENT)
            return None
    class Free:
        def __call__(self, _acl):
            pytest.fail("No ACL was allocated")
    class Library:
        acl_get_fd = Check()
        acl_free = Free()
    monkeypatch.setattr(module.ctypes, "CDLL", lambda *args, **kwargs: Library())
    assert module._has_acl(path) is False


def test_metadata_added_during_backup_refuses_commit(sample, monkeypatch):
    files, path = sample
    attributes = []
    monkeypatch.setattr(module.os, "listxattr", lambda _p: list(attributes), raising=False)
    original_backup = files.backup
    def backup_then_change(p):
        result = original_backup(p)
        attributes.append("com.example.changed")
        return result
    monkeypatch.setattr(files, "backup", backup_then_change)
    with pytest.raises(ValueError, match="extended attributes"):
        files.edit_text(str(path), "old", "new", files.info(str(path))["version"])
    assert path.read_bytes() == b"old"
    assert not list(path.parent.glob(".mcp-*.tmp"))


def test_multiple_hardlinks_still_refuse_overwrite(sample):
    files, path = sample
    alias = path.with_name("alias.txt")
    os.link(path, alias)
    with pytest.raises(ValueError, match="multiply linked"):
        files.edit_text(str(path), "old", "new", files.info(str(path))["version"])
    assert alias.read_bytes() == b"old"


native = pytest.mark.skipif(sys.platform != "darwin", reason="Actual macOS metadata; exercised on macOS CI")


@native
@pytest.mark.parametrize("attribute", ["com.example.mcp-test", "com.apple.ResourceFork"])
def test_native_xattr_and_resource_fork_are_rejected(sample, attribute):
    files, path = sample
    os.setxattr(path, attribute, b"metadata that must survive")
    try:
        with pytest.raises(ValueError, match="extended attributes"):
            files.edit_text(str(path), "old", "new", files.info(str(path))["version"])
        assert path.read_bytes() == b"old"
        assert os.getxattr(path, attribute) == b"metadata that must survive"
    finally:
        os.removexattr(path, attribute)


@native
def test_native_acl_is_rejected_without_removing_it(sample):
    files, path = sample
    subprocess.run(["/bin/chmod", "+a", f"{getpass.getuser()} allow read", str(path)], check=True)
    try:
        assert module._has_acl(path)
        with pytest.raises(ValueError, match="ACL"):
            files.edit_text(str(path), "old", "new", files.info(str(path))["version"])
        assert path.read_bytes() == b"old"
        assert module._has_acl(path)
    finally:
        subprocess.run(["/bin/chmod", "-N", str(path)], check=True)


@native
def test_native_executable_mode_survives_edit_and_overwrite(sample):
    files, path = sample
    path.chmod(0o751)
    files.edit_text(str(path), "old", "new", files.info(str(path))["version"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o751
    files.write(str(path), "next", overwrite=True)
    assert stat.S_IMODE(path.stat().st_mode) == 0o751


@native
def test_native_mode_change_during_backup_is_not_discarded(sample, monkeypatch):
    files, path = sample
    original_backup = files.backup
    def backup_then_change(p):
        result = original_backup(p)
        p.chmod(0o751)
        return result
    monkeypatch.setattr(files, "backup", backup_then_change)
    with pytest.raises(ValueError, match="changed"):
        files.edit_text(str(path), "old", "new", files.info(str(path))["version"])
    assert path.read_bytes() == b"old"
    assert stat.S_IMODE(path.stat().st_mode) == 0o751


@native
def test_native_immutable_file_is_rejected(sample):
    files, path = sample
    os.chflags(path, stat.UF_IMMUTABLE)
    try:
        with pytest.raises(ValueError, match="Immutable"):
            files.edit_text(str(path), "old", "new", files.info(str(path))["version"])
        assert path.read_bytes() == b"old"
    finally:
        os.chflags(path, 0)
