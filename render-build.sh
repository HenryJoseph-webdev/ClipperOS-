#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BGUTIL_VERSION="1.3.2"
BGUTIL_DIR="$ROOT/.render/bgutil-ytdlp-pot-provider"
DENO_DIR="$ROOT/.render/deno"

python -m pip install -r "$ROOT/requirements.txt"

if ! command -v ffmpeg >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ffmpeg
fi

if ! command -v deno >/dev/null 2>&1; then
  mkdir -p "$DENO_DIR"
  curl -fsSL https://deno.land/install.sh | DENO_INSTALL="$DENO_DIR" sh
fi
export PATH="$DENO_DIR/bin:$PATH"

if [ ! -d "$BGUTIL_DIR/server" ]; then
  mkdir -p "$ROOT/.render"
  git clone --depth 1 --branch "$BGUTIL_VERSION" \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    "$BGUTIL_DIR"
fi

cd "$BGUTIL_DIR/server"
deno install --node-modules-dir=auto --allow-scripts=npm:canvas --frozen
test -d "$BGUTIL_DIR/server/node_modules"
