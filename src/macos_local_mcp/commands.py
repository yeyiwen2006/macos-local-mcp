"""Opt-in, bounded current-user commands without a terminal or implicit shell.

POSIX process groups contain ordinary children, not deliberately daemonized
processes. This is not a sandbox. Output is memory-only; audit records exclude
arguments, environment values and output. Normal shutdown closes all jobs.
"""
from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import threading
import time
from uuid import uuid4

import psutil

from .files import Files
from .guard import Guard, PROJECT

MAX_RUNNING = 4
MAX_RETAINED = 32
MAX_OUTPUT_CHARS = 262144
ENCODINGS = ("utf-8", "gb18030", "utf-16-le", "cp1252")
_SECRET_ENV = {"OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "RUNTIME_KEY", "RUNTIME_API_KEY",
               "TUNNEL_API_KEY", "MCP_COMMAND"}
_PRIVATE_PREFIXES = ("MACOS_LOCAL_MCP_", "CONTROL_PLANE_", "MCP_TUNNEL_", "OPENAI_TUNNEL_")


def _private_environment(name: str) -> bool:
    name = name.upper()
    return name in _SECRET_ENV or name.startswith(_PRIVATE_PREFIXES)


def _integer(value: object, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} through {high}")
    return value


class Output:
    def __init__(self, limit: int):
        self.limit = limit
        self.text = ""
        self.total = 0
        self.lock = threading.Lock()

    def add(self, text: str) -> None:
        with self.lock:
            self.total += len(text)
            room = self.limit - len(self.text)
            if room > 0:
                self.text += text[:room]

    def read(self, offset: int, maximum: int) -> dict:
        with self.lock:
            if offset > len(self.text):
                raise ValueError("Output offset exceeds captured character count")
            end = min(len(self.text), offset + maximum)
            return {"text": self.text[offset:end], "next_offset": end,
                    "captured_chars": len(self.text), "total_chars": self.total,
                    "truncated": self.total > len(self.text)}


@dataclass
class Job:
    identifier: str
    timeout_seconds: int
    stdout: Output
    stderr: Output
    started: float = field(default_factory=time.monotonic)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    elapsed_seconds: float | None = None
    state: str = "running"
    exit_code: int | None = None
    pid: int | None = None
    error_type: str | None = None
    cancel_reason: str | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)
    worker: threading.Thread | None = None

    def request_stop(self, reason: str) -> None:
        with self.lock:
            if not self.done.is_set() and self.cancel_reason is None:
                self.cancel_reason = reason
                self.stop.set()

    def snapshot(self, stdout_offset: int = 0, stderr_offset: int = 0,
                 maximum: int = 65536) -> dict:
        with self.lock:
            return {"job_id": self.identifier, "pid": self.pid, "state": self.state,
                    "exit_code": self.exit_code,
                    "success": self.state == "completed" and self.exit_code == 0,
                    "started_at": self.started_at, "finished_at": self.finished_at,
                    "elapsed_seconds": self.elapsed_seconds if self.done.is_set()
                    else time.monotonic() - self.started,
                    "timeout_seconds": self.timeout_seconds, "error_type": self.error_type,
                    "stdout": self.stdout.read(stdout_offset, maximum),
                    "stderr": self.stderr.read(stderr_offset, maximum)}


class PosixProcess:
    """Keep the child PID unreaped until its own process group is cleaned up.

    Popen.poll() would reap the group leader and permit PID reuse. Instead use
    psutil's identity-aware zombie check, signal the owned group, then wait().
    No preexec_fn is used in this multithreaded service.
    """
    def __init__(self, executable: str, arguments: list[str], cwd: str, env: dict):
        self.process = subprocess.Popen(
            [executable, *arguments], cwd=cwd, env=env, shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            close_fds=True, start_new_session=True, bufsize=0)
        self.pid = self.process.pid
        try:
            self.identity = psutil.Process(self.pid)
            self.identity.create_time()
        except BaseException:
            # The direct child has not been reaped, so its group ID is still owned.
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=5)
            self.close()
            raise

    def exited(self) -> bool:
        try:
            return not self.identity.is_running() or self.identity.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return True

    def _signal(self, sig: int) -> None:
        # This check also accepts the unreaped zombie group leader. It never
        # targets an arbitrary PID supplied by a caller or a reused PID.
        if not self.identity.is_running():
            return
        try:
            if os.getpgid(self.pid) != self.pid:
                raise RuntimeError("Command process group identity changed")
            os.killpg(self.pid, sig)
        except ProcessLookupError:
            pass

    def terminate(self, grace: float = 0.15) -> int:
        if grace:
            self._signal(signal.SIGTERM)
            time.sleep(grace)
        self._signal(signal.SIGKILL)
        return self.process.wait(timeout=5)

    def close(self) -> None:
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()


class Commands:
    def __init__(self, guard: Guard):
        self.guard = guard
        self.files = Files(guard)
        self.enable_file = guard.state / "COMMANDS_ENABLED"
        self.jobs: dict[str, Job] = {}
        self.lock = threading.RLock()
        self.closed = False

    @property
    def enabled(self) -> bool:
        try:
            info = self.enable_file.lstat()
        except FileNotFoundError:
            return False
        # Refuse links and shared/writable approval markers. Approval is local-only.
        return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and (os.name != "posix" or not info.st_mode & 0o022)
                and (not hasattr(os, "getuid") or info.st_uid == os.getuid()))

    def status(self) -> dict:
        with self.lock:
            return {"enabled": self.enabled, "requires_local_opt_in": True,
                    "supported": os.name == "posix",
                    "running": sum(not job.done.is_set() for job in self.jobs.values()),
                    "retained": len(self.jobs), "max_running": MAX_RUNNING,
                    "max_retained": MAX_RETAINED, "desktop_focus_required": False,
                    "process_cleanup": "owned POSIX process group; not an OS sandbox"}

    def _lookup(self, identifier: str) -> Job:
        if not isinstance(identifier, str):
            raise ValueError("job_id must be a string returned by command_start")
        with self.lock:
            if identifier not in self.jobs:
                raise ValueError("Unknown or expired command job_id")
            return self.jobs[identifier]

    def _path(self, value: str) -> Path:
        if not isinstance(value, str) or not value or "\0" in value or not Path(value).is_absolute():
            raise ValueError("An absolute local path is required; no shell expansion")
        resolved = self.files.path(value)
        if resolved == PROJECT or PROJECT in resolved.parents:
            raise PermissionError("Command entry points and cwd cannot use service-protected paths")
        # Validate resolved destinations, but preserve executable symlinks so a
        # virtualenv/Homebrew interpreter retains its invocation-path semantics.
        return Path(value)

    def start(self, executable: str, arguments: list[str], cwd: str,
              timeout_seconds: int = 600, output_limit_chars: int = MAX_OUTPUT_CHARS,
              encoding: str = "utf-8", environment: dict[str, str] | None = None) -> dict:
        _integer(timeout_seconds, "timeout_seconds", 1, 86400)
        _integer(output_limit_chars, "output_limit_chars", 1024, MAX_OUTPUT_CHARS)
        if encoding not in ENCODINGS:
            raise ValueError("Unsupported output encoding")
        if not isinstance(arguments, list) or len(arguments) > 256 or any(
                not isinstance(arg, str) or "\0" in arg or len(arg) > 32768 for arg in arguments):
            raise ValueError("arguments must contain at most 256 NUL-free strings of at most 32768 characters")
        if sum(len(arg) for arg in arguments) > 131072:
            raise ValueError("Combined argument length exceeds 131072 characters")
        overrides = {} if environment is None else environment
        if not isinstance(overrides, dict) or len(overrides) > 64 or any(
                not isinstance(k, str) or not isinstance(v, str) or not k or "=" in k or
                "\0" in k + v or len(k) > 256 or len(v) > 32767 or _private_environment(k)
                for k, v in overrides.items()):
            raise ValueError("Invalid or service-private environment override")
        # Paths, argv and environment can all contain secrets: audit only counts/IDs.
        with self.guard.action("command_start", {"argument_count": len(arguments),
                                                 "timeout_seconds": timeout_seconds}):
            if not self.enabled:
                raise PermissionError("Commands are disabled. Enable locally with Enable-Commands.command")
            if os.name != "posix":
                raise OSError("Command execution requires macOS/POSIX")
            exe, directory = self._path(executable), self._path(cwd)
            if not exe.is_file() or not os.access(exe, os.X_OK):
                raise ValueError("executable must be an existing executable regular file")
            if not directory.is_dir():
                raise ValueError("cwd must be an existing directory")
            env = {k: v for k, v in os.environ.items() if not _private_environment(k)}
            env.update(overrides)
            with self.lock:
                if self.closed:
                    raise RuntimeError("Command executor is closed")
                if sum(not j.done.is_set() for j in self.jobs.values()) >= MAX_RUNNING:
                    raise RuntimeError("Command concurrency limit reached; wait or cancel an existing job")
                while len(self.jobs) >= MAX_RETAINED:
                    oldest = next((key for key, j in self.jobs.items() if j.done.is_set()), None)
                    if oldest is None:
                        raise RuntimeError("Command job capacity reached")
                    del self.jobs[oldest]
                job = Job(uuid4().hex, timeout_seconds, Output(output_limit_chars), Output(output_limit_chars))
                self.guard.audit({"tool": "command_job", "job_id": job.identifier, "result": "starting"})
                self.guard.check()
                if not self.enabled:
                    raise PermissionError("Command permission was revoked")
                process = PosixProcess(str(exe), list(arguments), str(directory), env)
                job.pid = process.pid
                self.jobs[job.identifier] = job
                job.worker = threading.Thread(target=self._watch, args=(job, process, encoding),
                                              name=f"command-{job.identifier[:8]}", daemon=True)
                try:
                    job.worker.start()
                except BaseException:
                    try:
                        process.terminate(grace=0)
                    finally:
                        process.close()
                        del self.jobs[job.identifier]
                    raise
                return job.snapshot(maximum=0)

    def _watch(self, job: Job, process: PosixProcess, encoding: str) -> None:
        selector = None
        state, code, error_type = "failed", None, None

        def drain(timeout: float) -> None:
            for key, _ in selector.select(timeout):
                output, decoder = key.data
                try:
                    block = os.read(key.fd, 16384)
                except BlockingIOError:
                    continue
                if block:
                    output.add(decoder.decode(block))
                else:
                    output.add(decoder.decode(b"", final=True))
                    selector.unregister(key.fileobj)

        try:
            selector = selectors.DefaultSelector()
            for stream, output in ((process.process.stdout, job.stdout), (process.process.stderr, job.stderr)):
                os.set_blocking(stream.fileno(), False)
                decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
                selector.register(stream, selectors.EVENT_READ, (output, decoder))
            while True:
                try:
                    self.guard.check()
                except PermissionError:
                    job.request_stop("paused")
                if not self.enabled:
                    job.request_stop("permission_revoked")
                if job.stop.is_set():
                    state = job.cancel_reason or "cancelled"
                    break
                drain(0.05)
                if process.exited():
                    state = "completed"
                    break
                if time.monotonic() - job.started >= job.timeout_seconds:
                    state = "timed_out"
                    break
        except BaseException as exc:
            error_type = type(exc).__name__
        finally:
            try:
                # Kill remaining ordinary children even after a successful root exit.
                code = process.terminate(grace=0 if state == "completed" else 0.15)
                deadline = time.monotonic() + 1
                while selector is not None and selector.get_map() and time.monotonic() < deadline:
                    drain(0.02)
                if selector is not None and selector.get_map():
                    state, error_type = "failed", "OutputDrainError"
            except Exception as exc:
                state, error_type = "failed", type(exc).__name__
            finally:
                if selector is not None:
                    selector.close()
                process.close()
            try:
                with self.guard.lock:
                    self.guard.audit({"tool": "command_job", "job_id": job.identifier,
                                      "result": state, "exit_code": code, "error_type": error_type})
            except OSError:
                state, error_type = "failed", "AuditWriteError"
            with job.lock:
                job.state, job.exit_code, job.error_type = state, code, error_type
                job.finished_at = datetime.now(timezone.utc).isoformat()
                job.elapsed_seconds = time.monotonic() - job.started
                job.done.set()

    def poll(self, job_id: str, stdout_offset: int = 0, stderr_offset: int = 0,
             max_chars: int = 65536, wait_seconds: int = 0) -> dict:
        _integer(stdout_offset, "stdout_offset", 0, MAX_OUTPUT_CHARS)
        _integer(stderr_offset, "stderr_offset", 0, MAX_OUTPUT_CHARS)
        _integer(max_chars, "max_chars", 1, 65536)
        _integer(wait_seconds, "wait_seconds", 0, 10)
        with self.guard.action("command_poll", {"job_id": job_id}):
            job = self._lookup(job_id)
        job.done.wait(wait_seconds)  # Never hold the guard while waiting.
        self.guard.check()
        return job.snapshot(stdout_offset, stderr_offset, max_chars)

    def cancel(self, job_id: str) -> dict:
        job = self._lookup(job_id)
        job.request_stop("cancelled")  # Remains available while paused or disabled.
        try:
            with self.guard.lock:
                self.guard.audit({"tool": "command_cancel", "job_id": job_id, "result": "requested"})
        except OSError:
            pass  # Audit failure must not block emergency termination.
        return {"job_id": job_id, "cancellation_requested": not job.done.is_set(),
                "finished": job.done.is_set()}

    def cancel_all(self, reason: str) -> None:
        with self.lock:
            for job in self.jobs.values():
                job.request_stop(reason)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            self.cancel_all("service_stopped")
            jobs = list(self.jobs.values())
        deadline = time.monotonic() + 7
        for job in jobs:
            job.done.wait(max(0, deadline - time.monotonic()))
