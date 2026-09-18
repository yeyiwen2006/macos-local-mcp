#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"

"$PYTHON" -c 'import sys; assert sys.version_info >= (3,13), "Python 3.13 or newer is required"'
if [ ! -x ".venv/bin/python" ]; then
  "$PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .

mkdir -p .local/tools
chmod 700 .local
MACOS_LOCAL_MCP_STATE="$PWD/.local" .venv/bin/python -c 'from macos_local_mcp.guard import Guard; Guard()'

if ! find .local/tools -type f -name 'tunnel-client' -perm -111 2>/dev/null | grep -q .; then
  echo "Downloading the latest official OpenAI Tunnel client..."
  .venv/bin/python - <<'PY'
import json, os, platform, re, urllib.request, zipfile
root = os.getcwd()
arch = {"arm64": "arm64", "x86_64": "amd64"}.get(platform.machine())
if not arch:
    raise SystemExit(f"Unsupported architecture: {platform.machine()}")
req = urllib.request.Request(
    "https://api.github.com/repos/openai/tunnel-client/releases/latest",
    headers={"User-Agent": "macos-local-mcp"},
)
with urllib.request.urlopen(req, timeout=30) as response:
    release = json.load(response)
pattern = re.compile(rf"^tunnel-client-v.*-darwin-{arch}\\.zip$")
assets = [a for a in release.get("assets", []) if pattern.match(a.get("name", ""))]
if len(assets) != 1:
    raise SystemExit("Official macOS Tunnel client release asset was not found.")
url = assets[0]["browser_download_url"]
if not url.startswith("https://github.com/openai/tunnel-client/releases/download/"):
    raise SystemExit("Unexpected Tunnel client download location.")
dest = os.path.join(root, ".local", "tools", release["tag_name"])
os.makedirs(dest, exist_ok=True)
archive = os.path.join(dest, "official-release.zip")
urllib.request.urlretrieve(url, archive)
with zipfile.ZipFile(archive) as z:
    z.extractall(dest)
for dirpath, _, filenames in os.walk(dest):
    for name in filenames:
        if name == "tunnel-client":
            path = os.path.join(dirpath, name)
            os.chmod(path, 0o755)
            print(path)
            raise SystemExit(0)
raise SystemExit("Downloaded archive did not contain tunnel-client.")
PY
fi

chmod +x ./*.command
echo
echo "Installed."
echo "Next: run ./Configure.command, then ./Permissions.command, then ./Start.command"
