#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BGUTIL_DIR="$ROOT/.render/bgutil-ytdlp-pot-provider"

cd "$BGUTIL_DIR/server"
node build/main.js --port 4416 > "$ROOT/bgutil-provider.log" 2>&1 &
PROVIDER_PID=$!

cleanup() {
  kill "$PROVIDER_PID" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:4416/ping >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$PROVIDER_PID" 2>/dev/null; then
    echo "=== BGUTIL PROVIDER LOG ==="
    cat "$ROOT/bgutil-provider.log" || true
    echo "=== END BGUTIL PROVIDER LOG ==="
    exit 1
  fi
  sleep 1
done

curl -fsS http://127.0.0.1:4416/ping >/dev/null

echo "=== BGUTIL PROVIDER LOG ==="
cat "$ROOT/bgutil-provider.log" || true
echo "=== END BGUTIL PROVIDER LOG ==="
echo "BgUtils provider is ready on 127.0.0.1:4416"

cd "$ROOT"
exec gunicorn --bind "0.0.0.0:${PORT:-10000}" --workers 1 production:application
