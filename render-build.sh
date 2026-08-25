#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BGUTIL_VERSION="1.3.2"
BGUTIL_DIR="$ROOT/.render/bgutil-ytdlp-pot-provider"

python -m pip install -r "$ROOT/requirements.txt"

command -v node >/dev/null 2>&1 || { echo "[bgutil] ERROR: Node.js is required but not available" >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "[bgutil] ERROR: npm is required but not available" >&2; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { echo "[clipper] ERROR: ffmpeg is required but not available" >&2; exit 1; }

if [ ! -d "$BGUTIL_DIR/server" ]; then
  mkdir -p "$ROOT/.render"
  echo "[bgutil] cloning provider v$BGUTIL_VERSION..."
  git clone --depth 1 --branch "$BGUTIL_VERSION" \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    "$BGUTIL_DIR"
fi

cd "$BGUTIL_DIR/server"
echo "[bgutil] installing provider server dependencies..."
npm ci
echo "[bgutil] compiling provider server..."
npx tsc
test -f "$BGUTIL_DIR/server/build/main.js"
