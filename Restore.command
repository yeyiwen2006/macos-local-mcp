#!/bin/bash
# Local-only backup browser/restorer. Never an MCP tool: the model cannot call this.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .local/backups ] || { echo "No backups yet." >&2; exit 1; }

PYTHON="$PWD/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Run ./Setup.command first." >&2
  exit 1
fi

"$PYTHON" - "$@" <<'PY'
import json, os, shutil, stat, sys
from pathlib import Path

state = Path(".local").resolve()
backups = state / "backups"
args = sys.argv[1:]

records = []
for folder in sorted(backups.iterdir()):
    meta = folder / "metadata.json"
    if meta.is_file():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            records.append((folder, data))
        except (OSError, ValueError):
            continue

if not records:
    print("No readable backups found.")
    raise SystemExit(0)

if not args or args[0] == "list":
    print(f"{len(records)} backup(s), newest first:\n")
    for index, (folder, data) in enumerate(reversed(records), 1):
        info = data.get("stat", {})
        size = info.get("bytes", "?")
        print(f"[{index}] {data.get('original_path', '?')} ({size} bytes)")
        print(f"     saved file: {folder / 'original.bin'}")
    print("\nRestore with: ./Restore.command restore <backup-index>")
    raise SystemExit(0)

if len(args) == 2 and args[0] == "restore":
    try:
        index = int(args[1])
    except ValueError:
        raise SystemExit("Index must be a number from the list above.")
    if not 1 <= index <= len(records):
        raise SystemExit(f"Index must be 1..{len(records)}.")
    folder, data = list(reversed(records))[index - 1]
    original = Path(data["original_path"])
    saved = folder / "original.bin"
    if not saved.is_file():
        raise SystemExit("Backup payload is missing.")
    if original.exists():
        answer = input(f"{original} already exists. Overwrite? [y/N] ")
        if answer.strip().lower() != "y":
            print("Aborted.")
            raise SystemExit(1)
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(saved, original)
    print(f"Restored {original} from {saved}.")
    print("Verify with your own tools; this script does not delete anything.")
    raise SystemExit(0)

raise SystemExit("Usage: ./Restore.command [list] | restore <backup-index>")
PY
