#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BGUTIL_VERSION="1.3.2"
BGUTIL_DIR="$ROOT/bgutil-provider"

python -m pip install -r "$ROOT/requirements.txt"

apt-get update
apt-get install -y ffmpeg curl ca-certificates git

if ! command -v node >/dev/null 2>&1 || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' ; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi

if [ ! -d "$BGUTIL_DIR/server" ]; then
  git clone --depth 1 --branch "$BGUTIL_VERSION" \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    "$BGUTIL_DIR"
fi

cd "$BGUTIL_DIR/server"
npm ci --no-audit --no-fund
npx tsc

test -f "$BGUTIL_DIR/server/build/main.js"
test -d "$BGUTIL_DIR/server/node_modules"
node --version
