"""Full current-user local file access with recoverable writes on macOS."""
from __future__ import annotations

import base64
import binascii
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from uuid import uuid4

from .guard import Guard, PROJECT

MAX_READ = 1024 * 1024
MAX_WRITE = 8 * 1024 * 1024
MAX_EDIT_FILE = 8 * 1024 * 1024
MAX_GREP_BYTES = 16 * 1024 * 1024
MAX_SEARCH_HITS = 200
MAX_SEARCH_FILES = 4000
MAX_GLOB_RESULTS = 500
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv"}

# Destructive file tools refuse these trees even though the current user could
# write them. Read tools stay unrestricted: the operator already granted full read.
PROTECTED_WRITE_PREFIXES = (
    "~/.ssh",
    "~/.gnupg",
    "~/.aws",
    "~/.config/gcloud",
    "~/Library/Keychains",
    "~/Library/Cookies",
)


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
        if mutation:
            for raw in PROTECTED_WRITE_PREFIXES:
                tree = valid_local_path(raw)
                if p == tree or tree in p.parents:
                    raise PermissionError(
                        f"Refusing to modify credential/sensitive path {tree}; the operator can do this locally"
                    )
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
        with p.open("r", encoding=encoding, errors="strict", newline="") as f:
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
        return {
            "path": str(p),
            "text": "".join(lines),
            "start_line": start_line,
            "lines": len(lines),
            "next_line": next_line,
            "encoding": encoding,
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
        try:
            xattrs = os.listxattr(p)
        except (AttributeError, OSError):
            xattrs = []
        if xattrs:
            raise ValueError("File has extended attributes; refusing an overwrite that could discard metadata")

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
                current = p.stat()
                if (current.st_mtime_ns, current.st_size, current.st_ino) != (
                    before.st_mtime_ns, before.st_size, before.st_ino
                ):
                    raise ValueError("File changed during backup; original left untouched")
                os.replace(temp, p)
            else:
                os.link(temp, p)
                temp.unlink()
        finally:
            if temp.exists():
                temp.unlink()
        return {
            "path": str(p),
            "bytes": len(data),
            "backup_path": backup,
            "modified_ns": p.stat().st_mtime_ns,
        }

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
        try:
            os.rename(src, dst)
        except OSError as exc:
            if exc.errno != 18:  # EXDEV: different volumes
                raise
            # Cross-volume fallback: copy to a temp file next to the destination,
            # fsync, rename into place, then recycle the original. Never deletes.
            from send2trash import send2trash
            dst.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=".mcp-move-", suffix=".tmp", dir=dst.parent)
            temp = Path(temp_name)
            try:
                if src.is_dir():
                    temp.unlink()
                    temp.rmdir()
                    import shutil
                    shutil.copytree(src, temp, symlinks=True)
                    os.rename(temp, dst)
                else:
                    self.regular(src)
                    with src.open("rb") as reader, os.fdopen(fd, "wb") as writer:
                        while block := reader.read(MAX_READ):
                            self.guard.check()
                            writer.write(block)
                        writer.flush()
                        os.fsync(writer.fileno())
                    os.chmod(temp, stat.S_IMODE(src.stat().st_mode))
                    os.rename(temp, dst)
            except BaseException:
                if temp.exists():
                    temp.unlink(missing_ok=True)
                raise
            send2trash(str(src))
            return {"source": str(src), "destination": str(dst), "cross_volume": True}
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

    def file_hash(self, path: str, algorithm: str = "sha256") -> dict:
        if algorithm not in ("sha256", "md5", "sha1"):
            raise ValueError("algorithm must be sha256, md5, or sha1")
        p = self.path(path)
        self.regular(p)
        digest = hashlib.new(algorithm)
        with p.open("rb") as f:
            while block := f.read(MAX_READ):
                self.guard.check()
                digest.update(block)
        return {"path": str(p), "algorithm": algorithm, "hex": digest.hexdigest(),
                "bytes": p.stat().st_size}

    def edit_text(self, path: str, old_string: str, new_string: str,
                  expected_modified_ns: int | None = None, replace_all: bool = False) -> dict:
        """Replace exact text, like a patch. Fails unless old_string matches exactly once
        (unless replace_all). The file must be UTF-8 text of at most 8 MiB."""
        if not isinstance(old_string, str) or not old_string:
            raise ValueError("old_string must be a nonempty string")
        if not isinstance(new_string, str):
            raise ValueError("new_string must be a string")
        if old_string == new_string:
            raise ValueError("old_string and new_string are identical; nothing to do")
        p = self.path(path, mutation=True)
        self.regular(p)
        if p.stat().st_size > MAX_EDIT_FILE:
            raise ValueError("edit_text_file only supports files up to 8 MiB; use write_file")
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("edit_text_file requires UTF-8 text; use write_file for binary") from exc
        count = text.count(old_string)
        if count == 0:
            raise ValueError("old_string not found; read the file again and copy the exact text")
        if count > 1 and not replace_all:
            raise ValueError(
                f"old_string matches {count} times; add surrounding lines to make it unique "
                "or pass replace_all=true"
            )
        updated = text.replace(old_string, new_string) if replace_all else text.replace(
            old_string, new_string, 1)
        result = self.write(path, updated, encoding="utf-8", overwrite=True,
                            expected_modified_ns=expected_modified_ns)
        return {**result, "replacements": count if replace_all else 1}

    def _pruned(self, dirs: list[str], root: Path) -> None:
        """In-place os.walk dir pruning: skip known junk dirs, symlinked dirs,
        and the service state tree (backups/audit are local-operator data)."""
        state = self.guard.state.resolve()  # walk roots may use /var symlink forms
        if root.resolve() == state or state in root.resolve().parents:
            dirs[:] = []  # Walk started inside the state tree; never descend.
            return
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS
            and not (root / d).is_symlink()
            and (root / d).resolve() != state
            and state not in (root / d).resolve().parents
        ]

    def search_text(self, path: str, pattern: str, is_regex: bool = False,
                    max_hits: int = MAX_SEARCH_HITS, max_files: int = MAX_SEARCH_FILES) -> dict:
        """Bounded grep over one file or a directory tree (skips .git/node_modules and
        binary-looking files). Returns file:line:line-text hits, never follows symlinks."""
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("pattern must be a nonempty string")
        if not 1 <= max_hits <= MAX_SEARCH_HITS or not 1 <= max_files <= MAX_SEARCH_FILES:
            raise ValueError(f"max_hits must be 1..{MAX_SEARCH_HITS} and max_files 1..{MAX_SEARCH_FILES}")
        if is_regex:
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"Invalid regular expression: {exc}") from exc
        else:
            needle = pattern.lower()

        def hit_line(line: str) -> bool:
            if is_regex:
                return compiled.search(line) is not None
            return needle in line.lower()

        p = self.path(path)
        if p.is_file():
            files = [p]
        elif p.is_dir():
            files = []
            for root, dirs, names in os.walk(p, followlinks=False):
                self._pruned(dirs, Path(root))
                self.guard.check()
                for name in names:
                    candidate = Path(root) / name
                    if candidate.is_symlink() or not candidate.is_file():
                        continue
                    files.append(candidate)
                    if len(files) >= max_files:
                        break
                if len(files) >= max_files:
                    break
        else:
            raise FileNotFoundError(str(p))

        hits, scanned, truncated_files = [], 0, False
        for candidate in files:
            if len(hits) >= max_hits or scanned >= max_files:
                truncated_files = True
                break
            try:
                if candidate.stat().st_size > MAX_GREP_BYTES:
                    continue
                with candidate.open("rb") as f:
                    head = f.read(8192)
                if b"\x00" in head:
                    continue  # Binary-looking file; never decode gigabytes of noise.
                with candidate.open("r", encoding="utf-8", errors="replace") as f:
                    for number, line in enumerate(f, 1):
                        self.guard.check()
                        if hit_line(line.rstrip("\r\n")):
                            hits.append({
                                "path": str(candidate),
                                "line": number,
                                "text": line.rstrip("\r\n")[:500],
                            })
                            if len(hits) >= max_hits:
                                break
                    scanned += 1
            except OSError:
                continue
        return {
            "hits": hits,
            "files_scanned": scanned,
            "truncated": len(hits) >= max_hits or truncated_files,
            "next_max_hits": max_hits,
        }

    def glob_files(self, path: str, pattern: str, limit: int = MAX_GLOB_RESULTS) -> dict:
        """List files under a directory matching a glob pattern (fnmatch syntax),
        skipping .git/node_modules-style trees. Never follows symlinks."""
        if not isinstance(pattern, str) or not pattern or len(pattern) > 512:
            raise ValueError("pattern must be a nonempty glob of at most 512 characters")
        if not 1 <= limit <= MAX_GLOB_RESULTS:
            raise ValueError(f"limit must be 1..{MAX_GLOB_RESULTS}")
        p = self.path(path)
        if not p.is_dir():
            raise FileNotFoundError(str(p))
        matches, truncated = [], False
        for root, dirs, names in os.walk(p, followlinks=False):
            self._pruned(dirs, Path(root))
            self.guard.check()
            for name in names:
                if fnmatch.fnmatch(name, pattern):
                    candidate = Path(root) / name
                    if candidate.is_symlink():
                        continue
                    try:
                        matches.append({"path": str(candidate), "bytes": candidate.stat().st_size})
                    except OSError:
                        continue
                    if len(matches) >= limit:
                        truncated = True
                        break
            if truncated:
                break
        return {"matches": matches, "truncated": truncated, "limit": limit}
