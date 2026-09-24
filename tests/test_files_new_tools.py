"""Tests for the opencode-style editing/search tools and write-protection."""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from macos_local_mcp.files import Files
from macos_local_mcp.guard import Guard


@pytest.fixture
def files(tmp_path):
    guard = Guard(tmp_path / "state")
    return Files(guard), guard, tmp_path


def test_edit_text_unique_match_replaces_once(files):
    f, _guard, tmp = files
    p = tmp / "code.py"
    f.write(str(p), "def a():\n    return 1\n\ndef b():\n    return 2\n")
    before = f.info(str(p))["modified_ns"]
    result = f.edit_text(str(p), "return 1", "return 42", expected_modified_ns=before)
    assert result["replacements"] == 1
    text = f.read_text(str(p))["text"]
    assert "return 42" in text and "return 2" in text
    assert Path(result["backup_path"]).read_text(encoding="utf-8") == "def a():\n    return 1\n\ndef b():\n    return 2\n"


def test_edit_text_requires_unique_match(files):
    f, _guard, tmp = files
    p = tmp / "dup.txt"
    f.write(str(p), "x = 1\ny = 1\n")
    with pytest.raises(ValueError, match="matches 2 times"):
        f.edit_text(str(p), "1", "2")
    result = f.edit_text(str(p), "1", "2", replace_all=True)
    assert result["replacements"] == 2
    assert f.read_text(str(p))["text"] == "x = 2\ny = 2\n"


def test_edit_text_conflict_detection_and_missing_needle(files):
    f, _guard, tmp = files
    p = tmp / "c.txt"
    f.write(str(p), "hello")
    with pytest.raises(ValueError, match="not found"):
        f.edit_text(str(p), "zzz", "q")
    with pytest.raises(ValueError, match="identical"):
        f.edit_text(str(p), "hello", "hello")
    # Stale modified_ns is checked after content match: use a needle that exists.
    before = f.info(str(p))["modified_ns"]
    f.write(str(p), "hello world", overwrite=True)
    with pytest.raises(ValueError, match="changed since"):
        f.edit_text(str(p), "hello", "q", expected_modified_ns=before)


def test_edit_text_rejects_binary(files):
    f, _guard, tmp = files
    p = tmp / "bad.bin"
    f.write(str(p), base64.b64encode(b"\xff\xfe\x00utf-8").decode(), encoding="base64")
    with pytest.raises(ValueError, match="UTF-8"):
        f.edit_text(str(p), "x", "y")


def test_search_text_single_file_and_tree(files):
    f, _guard, tmp = files
    f.write(str(tmp / "a.py"), "def hello():\n    pass\n")
    f.mkdir(str(tmp / "sub"))
    f.write(str(tmp / "sub" / "b.py"), "hello world\n")
    hits = f.search_text(str(tmp), "hello")["hits"]
    assert {Path(h["path"]).name for h in hits} == {"a.py", "b.py"}
    assert hits[0]["line"] == 1
    hits = f.search_text(str(tmp), r"def \w+", is_regex=True)["hits"]
    assert len(hits) == 1
    hits = f.search_text(str(tmp / "a.py"), "hello")["hits"]
    assert len(hits) == 1
    assert f.search_text(str(tmp), "absent-needle")["hits"] == []


def test_search_text_never_descends_into_guard_state(files):
    f, guard, tmp = files
    p = tmp / "leaf.txt"
    f.write(str(p), "marker-in-file\n")
    f.write(str(p), "marker-in-file\n", overwrite=True)  # backup holds the identical text
    hits = f.search_text(str(tmp), "marker-in-file")["hits"]
    assert all(guard.state not in Path(h["path"]).parents for h in hits)
    assert len(hits) == 1  # exactly the live file; the backup copy never surfaces


def test_glob_files_matches_and_skips(files):
    f, _guard, tmp = files
    f.mkdir(str(tmp / "node_modules"))
    f.write(str(tmp / "keep.py"), "x")
    f.write(str(tmp / "node_modules" / "junk.py"), "x")
    result = f.glob_files(str(tmp), "*.py")
    assert [Path(m["path"]).name for m in result["matches"]] == ["keep.py"]
    assert result["truncated"] is False
    with pytest.raises(ValueError):
        f.glob_files(str(tmp), "")


def test_file_hash_changes_with_content(files):
    f, _guard, tmp = files
    p = tmp / "h.txt"
    f.write(str(p), "one")
    first = f.file_hash(str(p))["hex"]
    f.write(str(p), "two", overwrite=True)
    second = f.file_hash(str(p), algorithm="md5")["hex"]
    assert first != second and len(first) == 64 and len(second) == 32
    with pytest.raises(ValueError):
        f.file_hash(str(p), algorithm="crc32")


def test_protected_write_prefixes_are_rejected(files):
    f, _guard, _tmp = files
    for target in ("~/.ssh/authorized_keys", "~/.gnupg/pubring.kbx", "~/Library/Cookies/x"):
        with pytest.raises(PermissionError, match="credential"):
            f.write(target, "nope")
    # Reads stay unrestricted: info on a sensitive path is allowed (no mutation).
    assert "path" in f.info("~/.ssh")


def test_move_same_volume_still_works(files):
    f, _guard, tmp = files
    src = tmp / "s.txt"
    f.write(str(src), "data")
    dst = tmp / "d.txt"
    result = f.move(str(src), str(dst))
    assert "cross_volume" not in result
    assert f.read_text(str(dst))["text"] == "data"
