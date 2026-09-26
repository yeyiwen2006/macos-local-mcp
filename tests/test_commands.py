from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
import tomllib

import psutil
import pytest

from macos_local_mcp import __version__
from macos_local_mcp.commands import Commands, Job, Output, _integer, _private_environment
from macos_local_mcp.control import main as control_main, set_commands_enabled
from macos_local_mcp.guard import Guard, PROJECT
from macos_local_mcp.server import build_server

native = pytest.mark.skipif(os.name != "posix", reason="Real POSIX process groups; exercised on macOS CI")


@pytest.fixture
def commands(tmp_path):
    result = Commands(Guard(tmp_path / "state"))
    yield result
    result.close()


def approve(commands):
    set_commands_enabled(commands.guard, True)


def start_python(commands, tmp_path, code, **kwargs):
    return commands.start(sys.executable, ["-u", "-c", code], str(tmp_path), **kwargs)


def finished(commands, started, timeout=8):
    job = commands.jobs[started["job_id"]]
    assert job.done.wait(timeout), "Command watchdog did not finish"
    snapshot = job.snapshot()
    assert snapshot["error_type"] is None, snapshot
    return snapshot


def wait_output(commands, started, timeout=5):
    deadline = time.monotonic() + timeout
    job = commands.jobs[started["job_id"]]
    while time.monotonic() < deadline:
        text = job.stdout.read(0, 65536)["text"]
        if "\n" in text:
            return text
        time.sleep(.01)
    pytest.fail("Command did not produce its readiness line")


def test_version_and_readme_match():
    metadata = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["version"] == __version__
    text = (PROJECT / "README.md").read_text(encoding="utf-8")
    assert f"当前版本为 {__version__}。" in text
    assert "当前 0.1.1 版本为" not in text


def test_disabled_by_default_and_local_control_requires_approval(commands, monkeypatch, capsys):
    assert not commands.enabled
    with pytest.raises(PermissionError, match="disabled"):
        commands.start("/usr/bin/true", [], "/tmp")
    monkeypatch.setenv("MACOS_LOCAL_MCP_STATE", str(commands.guard.state))
    with pytest.raises(SystemExit):
        control_main(["enable-commands"])
    assert not commands.enabled
    control_main(["enable-commands", "--accept-command-risk"])
    assert commands.enabled
    control_main(["status"])
    assert f'"version": "{__version__}"' in capsys.readouterr().out
    control_main(["disable-commands"])
    assert not commands.enabled


def test_command_approval_does_not_resume_pause(commands):
    commands.guard.pause()
    approve(commands)
    assert commands.enabled
    with pytest.raises(PermissionError, match="paused"):
        commands.start("/usr/bin/true", [], "/tmp")


@pytest.mark.parametrize("value", [True, False, 0, 86401, 1.5, "1", None])
def test_timeout_is_a_bounded_integer(value):
    with pytest.raises(ValueError):
        _integer(value, "timeout_seconds", 1, 86400)


def test_output_pagination_and_truncation_count_characters():
    output = Output(4)
    output.add("中🙂文abc")
    assert output.read(0, 2) == {"text": "中🙂", "next_offset": 2,
                                 "captured_chars": 4, "total_chars": 6, "truncated": True}
    assert output.read(2, 10)["text"] == "文a"
    with pytest.raises(ValueError):
        output.read(5, 2)


@pytest.mark.parametrize("changes", [
    {"arguments": "ls"}, {"arguments": ["bad\0arg"]}, {"arguments": [1]},
    {"arguments": [""] * 257}, {"arguments": ["x" * 32769]},
    {"arguments": ["x" * 32768] * 5}, {"timeout_seconds": True},
    {"output_limit_chars": 1023}, {"output_limit_chars": 262145},
    {"encoding": "not-a-codec"}, {"environment": {"BAD=KEY": "x"}},
    {"environment": {"X": "\0"}}, {"environment": {"X": 123}},
    {"environment": {"CONTROL_PLANE_API_KEY": "secret"}},
    {"environment": {"MACOS_LOCAL_MCP_STATE": "/tmp/other"}},
])
def test_validation_rejects_before_launch(commands, changes):
    args = dict(executable="/usr/bin/true", arguments=[], cwd="/tmp")
    args.update(changes)
    with pytest.raises(ValueError):
        commands.start(**args)
    assert commands.jobs == {}


@pytest.mark.parametrize("name", ["CONTROL_PLANE_API_KEY", "CONTROL_PLANE_TUNNEL_ID", "MCP_COMMAND",
                                 "OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "MACOS_LOCAL_MCP_STATE",
                                 "MCP_TUNNEL_TOKEN", "OPENAI_TUNNEL_TOKEN", "runtime_key"])
def test_service_environment_is_private(name):
    assert _private_environment(name)
    assert not _private_environment("BUILD_CONFIGURATION")


def test_unknown_jobs_and_invalid_offsets(commands):
    with pytest.raises(ValueError):
        commands.cancel("not-this-service")
    with pytest.raises(ValueError):
        commands.cancel(123)
    with pytest.raises(ValueError):
        commands.poll("missing", wait_seconds=11)
    with pytest.raises(ValueError):
        commands.poll("missing", stdout_offset=-1)
    with pytest.raises(ValueError):
        commands.poll("missing")


def test_protected_paths_rejected_including_resolved_alias(commands, tmp_path):
    for path in (str(commands.guard.state), str(PROJECT), str(PROJECT / "src")):
        with pytest.raises(PermissionError):
            commands._path(path)
    with pytest.raises(ValueError):
        commands._path("relative/path")
    with pytest.raises(ValueError):
        commands._path("~/project")


@native
def test_approval_symlink_and_shared_marker_fail_closed(commands, tmp_path):
    other = tmp_path / "operator-marker"
    other.write_text("yes")
    commands.enable_file.symlink_to(other)
    assert not commands.enabled
    with pytest.raises(ValueError, match="symlink"):
        approve(commands)
    set_commands_enabled(commands.guard, False)
    assert other.exists()
    approve(commands)
    commands.enable_file.chmod(0o666)
    assert not commands.enabled


def test_mcp_tool_surface_and_no_remote_approval(commands):
    server, runtime = build_server(commands.guard)
    try:
        tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
        assert {"command_start", "command_poll", "command_cancel"} <= tools.keys()
        assert not {"enable_commands", "service_resume", "disable_commands"} & tools.keys()
        assert tools["command_start"].annotations.destructiveHint
        assert tools["command_start"].annotations.openWorldHint
        assert tools["command_poll"].annotations.readOnlyHint
        assert tools["command_cancel"].annotations.destructiveHint
        assert runtime._desktop is None
        assert not runtime.commands.enabled
    finally:
        runtime.commands.close()


@native
def test_real_argv_cwd_stdin_and_separate_streams(commands, tmp_path):
    approve(commands)
    cwd = tmp_path / "space 中文"
    cwd.mkdir()
    values = ["a b", "中🙂", "'quoted'", "$(touch SHOULD_NOT_EXIST)", "x;y", "*.txt"]
    code = "import sys,os,json; print(json.dumps([sys.argv[1:],os.getcwd(),sys.stdin.read()],ensure_ascii=False)); print('stderr中文',file=sys.stderr)"
    result = finished(commands, commands.start(sys.executable, ["-u", "-c", code, *values], str(cwd)))
    assert result["success"] and result["exit_code"] == 0
    assert json.loads(result["stdout"]["text"]) == [values, str(cwd.resolve()), ""]
    assert result["stderr"]["text"] == "stderr中文\n"
    assert not (cwd / "SHOULD_NOT_EXIST").exists()
    assert not result["stdout"]["truncated"]


@native
def test_nonzero_exit_and_explicit_shell(commands, tmp_path):
    approve(commands)
    result = finished(commands, start_python(commands, tmp_path, "raise SystemExit(7)"))
    assert result["state"] == "completed" and result["exit_code"] == 7 and not result["success"]
    result = finished(commands, commands.start("/bin/sh", ["-c", "printf shell-ok"], str(tmp_path)))
    assert result["stdout"]["text"] == "shell-ok" and result["success"]


@native
@pytest.mark.parametrize("encoding,text", [("utf-8", "中🙂"), ("utf-16-le", "中🙂"),
                                           ("gb18030", "中文"), ("cp1252", "café")])
def test_incremental_decoding(commands, tmp_path, encoding, text):
    approve(commands)
    code = f"import os,time; data={text!r}.encode({encoding!r}); [(os.write(1,bytes([b])),time.sleep(.01)) for b in data]"
    result = finished(commands, start_python(commands, tmp_path, code, encoding=encoding))
    assert result["success"] and result["stdout"]["text"] == text


@native
def test_output_cap_drains_both_pipes_and_offsets(commands, tmp_path):
    approve(commands)
    code = "import os; [(os.write(1,b'a'*4096),os.write(2,b'b'*4096)) for _ in range(100)]"
    result = finished(commands, start_python(commands, tmp_path, code, output_limit_chars=1024))
    assert result["success"]
    for stream in ("stdout", "stderr"):
        assert result[stream]["captured_chars"] == 1024
        assert result[stream]["total_chars"] == 409600
        assert result[stream]["truncated"]
    page = commands.poll(result["job_id"], stdout_offset=100, stderr_offset=101, max_chars=7)
    assert page["stdout"]["text"] == "a" * 7
    assert page["stdout"]["next_offset"] == 107
    assert page["stderr"]["next_offset"] == 108


@native
def test_environment_filter_and_content_free_audit(commands, tmp_path, monkeypatch):
    approve(commands)
    monkeypatch.setenv("CONTROL_PLANE_API_KEY", "inherited-secret-123")
    monkeypatch.setenv("OPENAI_API_KEY", "another-secret-456")
    monkeypatch.setenv("MCP_COMMAND", "private-launch-command")
    code = "import os,json; print(json.dumps({k:os.environ.get(k) for k in ['CONTROL_PLANE_API_KEY','OPENAI_API_KEY','MACOS_LOCAL_MCP_STATE','MCP_COMMAND','BUILD_TEST']}))"
    result = finished(commands, start_python(commands, tmp_path, code, environment={"BUILD_TEST": "build-secret-789"}))
    assert result["success"]
    env = json.loads(result["stdout"]["text"])
    assert env == {"CONTROL_PLANE_API_KEY": None, "OPENAI_API_KEY": None, "MACOS_LOCAL_MCP_STATE": None,
                   "MCP_COMMAND": None, "BUILD_TEST": "build-secret-789"}
    audit = "".join(p.read_text(encoding="utf-8") for p in (commands.guard.state / "audit").glob("*.jsonl"))
    for value in (code, "build-secret-789", "inherited-secret-123", "another-secret-456", str(tmp_path)):
        assert value not in audit


@native
@pytest.mark.parametrize("stop", ["cancel", "pause", "disable", "close", "timeout"])
def test_stops_running_jobs_and_sigterm_resistant_children(commands, tmp_path, stop):
    approve(commands)
    code = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(60)"
    started = start_python(commands, tmp_path, code, timeout_seconds=1 if stop == "timeout" else 30)
    wait_output(commands, started)
    identity = psutil.Process(started["pid"])
    if stop == "cancel":
        commands.cancel(started["job_id"])
    elif stop == "pause":
        commands.guard.pause()
    elif stop == "disable":
        set_commands_enabled(commands.guard, False)
    elif stop == "close":
        commands.close()
    result = finished(commands, started)
    assert result["state"] == {"cancel": "cancelled", "pause": "paused", "disable": "permission_revoked",
                               "close": "service_stopped", "timeout": "timed_out"}[stop]
    assert not result["success"] and result["exit_code"] is not None
    assert not identity.is_running()
    # Even a paused service accepts cancellation of its own completed jobs.
    commands.cancel(started["job_id"])


@native
@pytest.mark.parametrize("root_exits", [False, True])
def test_ordinary_descendants_are_cleaned_up(commands, tmp_path, root_exits):
    approve(commands)
    child = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"
    code = f"import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c',{child!r}]); print(p.pid,flush=True); "
    code += "time.sleep(.2)" if root_exits else "time.sleep(60)"
    started = start_python(commands, tmp_path, code)
    child_pid = int(wait_output(commands, started).splitlines()[0])
    if not root_exits:
        commands.cancel(started["job_id"])
    result = finished(commands, started)
    assert result["state"] == ("completed" if root_exits else "cancelled"), result
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            if psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE:
                break
        except psutil.NoSuchProcess:
            break
        time.sleep(.02)
    else:
        pytest.fail("An ordinary command descendant survived group cleanup")


@native
def test_poll_wait_releases_global_guard_and_cancel_works_while_paused(commands, tmp_path):
    approve(commands)
    started = start_python(commands, tmp_path, "import time; print('ready',flush=True); time.sleep(60)")
    wait_output(commands, started)
    polling = threading.Event()
    def poller():
        polling.set()
        try:
            commands.poll(started["job_id"], wait_seconds=10)
        except PermissionError:
            pass
    thread = threading.Thread(target=poller)
    thread.start()
    polling.wait(1)
    assert commands.guard.lock.acquire(timeout=.5)
    commands.guard.lock.release()
    commands.guard.pause()
    commands.cancel(started["job_id"])
    thread.join(4)
    assert not thread.is_alive()
    assert not finished(commands, started)["success"]


@native
def test_limits_retention_and_close_rejects_new_jobs(commands, tmp_path, monkeypatch):
    import macos_local_mcp.commands as module
    approve(commands)
    monkeypatch.setattr(module, "MAX_RUNNING", 1)
    monkeypatch.setattr(module, "MAX_RETAINED", 2)
    first = start_python(commands, tmp_path, "import time; time.sleep(60)")
    with pytest.raises(RuntimeError, match="concurrency"):
        start_python(commands, tmp_path, "pass")
    commands.cancel(first["job_id"])
    finished(commands, first)
    for _ in range(3):
        finished(commands, start_python(commands, tmp_path, "pass"))
    assert len(commands.jobs) == 2
    with pytest.raises(ValueError, match="expired"):
        commands.poll(first["job_id"])
    commands.close()
    with pytest.raises(RuntimeError, match="closed"):
        start_python(commands, tmp_path, "pass")


@native
def test_executable_symlink_is_preserved_and_cwd_alias_checked(commands, tmp_path):
    approve(commands)
    alias = tmp_path / "python-alias"
    alias.symlink_to(sys.executable)
    result = finished(commands, commands.start(str(alias), ["-c", "import sys; print(sys.executable)"], str(tmp_path)))
    assert result["success"] and result["stdout"]["text"].strip() == str(alias)
    protected = tmp_path / "protected-alias"
    protected.symlink_to(commands.guard.state, target_is_directory=True)
    with pytest.raises(PermissionError):
        commands.start(sys.executable, ["-c", "pass"], str(protected))
    with pytest.raises(ValueError):
        commands.start(str(tmp_path), [], str(tmp_path))


@pytest.mark.skipif(sys.platform != "darwin", reason="Actual macOS MCP stdio host")
def test_macos_stdio_command_and_session_shutdown(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    guard = Guard(tmp_path / "stdio-state")
    set_commands_enabled(guard, True)
    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-m", "macos_local_mcp"],
                                       env={**os.environ, "MACOS_LOCAL_MCP_STATE": str(guard.state)})
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool("command_start", {
                    "executable": sys.executable, "arguments": ["-c", "import time; time.sleep(60)"],
                    "cwd": str(tmp_path)})
                assert not result.isError
                payload = json.loads(result.content[0].text)
                identity = psutil.Process(payload["pid"])
        return identity
    identity = asyncio.run(exercise())
    deadline = time.monotonic() + 5
    while identity.is_running() and time.monotonic() < deadline:
        time.sleep(.02)
    assert not identity.is_running()
