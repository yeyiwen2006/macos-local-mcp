"""Full current-user local file access with recoverable writes on macOS."""
from __future__ import annotations

import base64
import binascii
import ctypes
import errno
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from uuid import uuid4

from .guard import Guard, PROJECT
from .text_edit import replace_text_bytes

MAX_READ = 1024 * 1024
MAX_WRITE = 8 * 1024 * 1024


def _version(st: os.stat_result) -> str:
    """A stat identity/version token, not a content hash."""
    return "v1:" + ":".join(str(getattr(st, name)) for name in
                            ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    # Windows Python 3.13 reports ctime differently for paths and open fds.
    # Compare ctime within each API across the read, and identity across APIs.
    return all(getattr(left, name) == getattr(right, name) for name in
               ("st_dev", "st_ino", "st_size", "st_mtime_ns"))


def _has_acl(p: Path) -> bool:
    """Inspect Darwin ACL metadata through an open fd and fail closed on errors."""
    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    get_acl = library.acl_get_fd
    get_acl.argtypes = [ctypes.c_int]
    get_acl.restype = ctypes.c_void_p
    free_acl = library.acl_free
    free_acl.argtypes = [ctypes.c_void_p]
    free_acl.restype = ctypes.c_int
    fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        ctypes.set_errno(0)
        acl = get_acl(fd)
        if not acl:
            error = ctypes.get_errno()
            # Darwin filesec_get_property uses ENOENT for an absent ACL.
            # Using an already-open fd removes pathname-not-found ambiguity.
            if error == errno.ENOENT:
                return False
            raise OSError(error, "Unable to inspect file ACL", str(p))
        try:
            return True
        finally:
            if free_acl(acl) != 0:
                raise OSError(ctypes.get_errno(), "Unable to release file ACL", str(p))
    finally:
        os.close(fd)


def lexical_local_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("An absolute local file path is required")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Relative paths are unsupported")
    return path


def valid_local_path(value: str) -> Path:
    return lexical_local_path(value).resolve()


class Files:
    def __init__(self, guard: Guard):
        self.guard = guard

    def path(self, value: str, *, mutation: bool = False) -> Path:
        lexical = lexical_local_path(value)
        if mutation and lexical.exists() and lexical.is_symlink():
            raise ValueError("Mutating a symlink is unsupported; choose the actual path explicitly")
        p = valid_local_path(value)
        if p == self.guard.state or self.guard.state in p.parents:
            raise PermissionError("Service credentials, backups and audit data are local-operator only")
        if mutation and (p == PROJECT or PROJECT in p.parents):
            raise PermissionError("Use local controls to change this service")
        return p

    def protect_tree(self, p: Path) -> None:
        protected = [
            PROJECT,
            self.guard.state,
            Path.home().resolve(),
            Path("/System"),
            Path("/Library"),
            Path("/Applications"),
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
        ]
        if p == Path("/") or any(p == q or p in q.parents for q in protected):
            raise PermissionError("Refusing to move or recycle a protected directory tree")

    @staticmethod
    def regular(p: Path) -> None:
        st = p.stat()
        if not p.is_file() or not stat.S_ISREG(st.st_mode):
            raise ValueError("A regular file is required")

    def info(self, path: str) -> dict:
        p = self.path(path)
        s = p.stat()
        return {
            "path": str(p),
            "directory": p.is_dir(),
            "bytes": s.st_size,
            "modified_ns": s.st_mtime_ns,
            "created_ns": s.st_birthtime_ns if hasattr(s, "st_birthtime_ns") else s.st_ctime_ns,
            "version": _version(s),
        }

    def list_directory(self, path: str, limit: int = 200, offset: int = 0) -> dict:
        if not 1 <= limit <= 1000 or offset < 0 or offset > 100000:
            raise ValueError("limit must be 1..1000 and offset 0..100000")
        p = self.path(path)
        result = []
        with os.scandir(p) as entries:
            for index, entry in enumerate(entries):
                self.guard.check()
                if index < offset:
                    continue
                if len(result) >= limit:
                    return {"entries": result, "next_offset": index, "order": "filesystem"}
                try:
                    s = entry.stat(follow_symlinks=False)
                    result.append({
                        "name": entry.name,
                        "path": entry.path,
                        "directory": entry.is_dir(follow_symlinks=False),
                        "link": entry.is_symlink(),
                        "bytes": s.st_size,
                    })
                except OSError:
                    result.append({"name": entry.name, "accessible": False})
        return {"entries": result, "next_offset": None, "order": "filesystem"}

    def read_binary(self, path: str, offset: int = 0, length: int = MAX_READ) -> dict:
        if offset < 0 or not 1 <= length <= MAX_READ:
            raise ValueError("offset must be nonnegative and length 1..1048576")
        p = self.path(path)
        self.regular(p)
        with p.open("rb") as f:
            f.seek(offset)
            data = f.read(length)
            more = bool(f.read(1))
        return {
            "path": str(p),
            "base64": base64.b64encode(data).decode("ascii"),
            "offset": offset,
            "bytes": len(data),
            "next_offset": offset + len(data) if more else None,
        }

    def read_text(self, path: str, start_line: int = 1, max_lines: int = 500,
                  encoding: str = "utf-8-sig") -> dict:
        if start_line < 1 or start_line > 1000000 or not 1 <= max_lines <= 5000:
            raise ValueError("start_line must be 1..1000000, max_lines 1..5000")
        if encoding not in ("utf-8", "utf-8-sig", "utf-16", "gb18030"):
            raise ValueError("Supported encodings: utf-8, utf-8-sig, utf-16, gb18030")
        p = self.path(path)
        self.regular(p)
        lines, size, next_line = [], 0, None
        before_path = p.stat()
        with p.open("r", encoding=encoding, errors="strict", newline="") as f:
            before = os.fstat(f.fileno())
            if not _same_file(before, before_path):
                raise ValueError("File changed while opening; read it again")
            for number in range(1, start_line + max_lines + 1):
                self.guard.check()
                line = f.readline(MAX_READ + 1)
                if not line:
                    break
                if len(line) > MAX_READ:
                    raise ValueError("Line exceeds text limit; use read_binary in chunks")
                if number < start_line:
                    continue
                if len(lines) == max_lines or size + len(line) > MAX_READ:
                    next_line = number
                    break
                lines.append(line)
                size += len(line)
            if _version(os.fstat(f.fileno())) != _version(before) or _version(p.stat()) != _version(before_path):
                raise ValueError("File changed while reading; read it again")
        return {
            "path": str(p),
            "text": "".join(lines),
            "start_line": start_line,
            "lines": len(lines),
            "next_line": next_line,
            "encoding": encoding,
            "version": _version(before_path),
        }

    def backup(self, p: Path) -> str:
        self.regular(p)
        folder = self.guard.state / "backups" / uuid4().hex
        folder.mkdir(parents=True)
        try:
            folder.chmod(0o700)
        except OSError:
            pass
        target = folder / "original.bin"
        with p.open("rb") as src, target.open("xb") as dst:
            while block := src.read(MAX_READ):
                self.guard.check()
                dst.write(block)
            dst.flush()
            os.fsync(dst.fileno())
        (folder / "metadata.json").write_text(
            json.dumps({"original_path": str(p), "stat": self.info(str(p))}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(target)

    @staticmethod
    def ordinary_overwrite(p: Path) -> None:
        st = p.lstat()
        if stat.S_ISLNK(st.st_mode):
            raise ValueError("Overwriting a symlink is unsupported")
        if st.st_nlink > 1:
            raise ValueError("Overwriting a multiply linked file is unsupported")
        flags = getattr(st, "st_flags", 0)
        immutable = getattr(stat, "UF_IMMUTABLE", 0) | getattr(stat, "SF_IMMUTABLE", 0)
        if flags & immutable:
            raise ValueError("Immutable files cannot be overwritten")
        # Portable Windows tests have no xattr API; on Darwin an unavailable or
        # failed metadata check must never be mistaken for an ordinary file.
        listxattr = getattr(os, "listxattr", None)
        if listxattr is None:
            if sys.platform == "darwin":
                raise OSError("Extended attribute inspection is unavailable")
            xattrs = []
        else:
            xattrs = listxattr(p)
        if xattrs:
            raise ValueError("File has extended attributes; refusing an overwrite that could discard metadata")
        if sys.platform == "darwin" and _has_acl(p):
            raise ValueError("File has an ACL; refusing an overwrite that could discard metadata")

    def write(self, path: str, content: str, encoding: str = "utf-8", overwrite: bool = False,
              expected_modified_ns: int | None = None) -> dict:
        if encoding == "utf-8":
            data = content.encode("utf-8")
        elif encoding == "base64":
            try:
                data = base64.b64decode(content, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("Invalid base64 data") from exc
        else:
            raise ValueError("encoding must be utf-8 or base64")
        if len(data) > MAX_WRITE:
            raise ValueError("Write limit is 8 MiB per call")

        return self._write_bytes(path, data, overwrite, expected_modified_ns)

    def _write_bytes(self, path: str, data: bytes, overwrite: bool = False,
                     expected_modified_ns: int | None = None,
                     expected_version: str | None = None) -> dict:
        if len(data) > MAX_WRITE:
            raise ValueError("Write limit is 8 MiB per call")

        p = self.path(path, mutation=True)
        if not p.parent.exists() or not p.parent.is_dir():
            raise FileNotFoundError(f"Parent directory does not exist: {p.parent}")
        if p.exists() and not overwrite:
            raise FileExistsError("File exists; explicitly set overwrite=true after reading it")

        before = p.stat() if p.exists() else None
        if before:
            self.regular(p)
            self.ordinary_overwrite(p)
        if expected_modified_ns is not None and (before is None or before.st_mtime_ns != expected_modified_ns):
            raise ValueError("File changed since it was read; read it again before replacing")
        if expected_version is not None and (before is None or _version(before) != expected_version):
            raise ValueError("File changed since it was read; read it again before replacing")

        backup = self.backup(p) if before else None
        fd, temp_name = tempfile.mkstemp(prefix=".mcp-", suffix=".tmp", dir=p.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            if before:
                os.chmod(temp, stat.S_IMODE(before.st_mode))
            self.guard.check()
            if before:
                self.ordinary_overwrite(p)
                current = p.stat()
                if _version(current) != _version(before):
                    raise ValueError("File changed during backup; original left untouched")
                os.replace(temp, p)
            else:
                os.link(temp, p)
                temp.unlink()
        finally:
            if temp.exists():
                temp.unlink()
        after = p.stat()
        return {
            "path": str(p),
            "bytes": len(data),
            "backup_path": backup,
            "modified_ns": after.st_mtime_ns,
            "version": _version(after),
        }

    def edit_text(self, path: str, old_text: str, new_text: str, expected_version: str,
                  encoding: str = "utf-8-sig") -> dict:
        """Replace one exact occurrence, retaining all bytes outside its span."""
        if not isinstance(expected_version, str) or not expected_version:
            raise ValueError("expected_version must be returned by file_info or read_text_file")
        p = self.path(path, mutation=True)
        self.regular(p)
        self.ordinary_overwrite(p)
        self.guard.check()
        before_path = p.stat()
        with p.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if _version(before_path) != expected_version or not _same_file(before, before_path):
                raise ValueError("File changed since it was read; read it again before editing")
            if before.st_size > MAX_WRITE:
                raise ValueError("Text edit limit is 8 MiB")
            data = stream.read(MAX_WRITE + 1)
            if len(data) > MAX_WRITE:
                raise ValueError("Text edit limit is 8 MiB")
            if _version(os.fstat(stream.fileno())) != _version(before) or _version(p.stat()) != expected_version:
                raise ValueError("File changed while reading; read it again before editing")
        updated, change = replace_text_bytes(data, old_text, new_text, encoding)
        self.guard.check()
        if len(updated) > MAX_WRITE:
            raise ValueError("Text edit limit is 8 MiB")
        if not change["changed"]:
            self.ordinary_overwrite(p)
            if _version(p.stat()) != expected_version:
                raise ValueError("File changed while editing; read it again")
            return {"path": str(p), "bytes": len(data), "backup_path": None,
                    "modified_ns": before.st_mtime_ns, "version": expected_version, **change}
        result = self._write_bytes(path, updated, overwrite=True, expected_version=expected_version)
        return {**result, **change}

    def mkdir(self, path: str) -> dict:
        p = self.path(path, mutation=True)
        self.guard.check()
        p.mkdir(parents=True, exist_ok=True)
        return {"path": str(p)}

    def move(self, source: str, destination: str) -> dict:
        src = self.path(source, mutation=True)
        dst = self.path(destination, mutation=True)
        self.protect_tree(src)
        if dst.exists():
            raise FileExistsError("Destination already exists; move never overwrites")
        self.guard.check()
        os.rename(src, dst)
        return {"source": str(src), "destination": str(dst)}

    def recycle(self, path: str) -> dict:
        from send2trash import send2trash
        p = self.path(path, mutation=True)
        self.protect_tree(p)
        if not p.exists():
            raise FileNotFoundError(str(p))
        self.guard.check()
        send2trash(str(p))
        return {"path": str(p), "recycled": True}
