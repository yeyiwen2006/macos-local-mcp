from types import SimpleNamespace

import pytest

import macos_local_mcp.commands as module
from macos_local_mcp.commands import PosixProcess


@pytest.mark.parametrize("exited,live", [(False, False), (False, True), (True, False), (True, True)])
def test_darwin_empty_group_eperm_is_not_a_real_permission_failure(monkeypatch, exited, live):
    process = PosixProcess.__new__(PosixProcess)
    process.pid = 12345
    process.process = SimpleNamespace(returncode=None)
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(process, "exited", lambda: exited)
    monkeypatch.setattr(process, "_has_live_group_members", lambda: live)
    def denied(pid, sig):
        assert pid == 12345
        raise PermissionError("synthetic permission error")
    monkeypatch.setattr(module.os, "killpg", denied, raising=False)
    if exited and not live:
        process._signal(9)
    else:
        with pytest.raises(PermissionError):
            process._signal(9)


def test_process_group_visibility_failure_is_not_treated_as_empty(monkeypatch):
    process = PosixProcess.__new__(PosixProcess)
    process.pid = 12345
    monkeypatch.setattr(module.psutil, "pids", lambda: [12])
    def denied(pid):
        raise PermissionError("synthetic visibility denial")
    monkeypatch.setattr(module.os, "getpgid", denied, raising=False)
    with pytest.raises(PermissionError):
        process._has_live_group_members()


def test_reaped_process_never_signals_a_potentially_reused_group(monkeypatch):
    process = PosixProcess.__new__(PosixProcess)
    process.pid = 12345
    process.process = SimpleNamespace(returncode=0)
    def forbidden(*args):
        raise AssertionError("must not signal after reaping")
    monkeypatch.setattr(module.os, "killpg", forbidden, raising=False)
    process._signal(9)
