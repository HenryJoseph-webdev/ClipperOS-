#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BGUTIL_DIR="$ROOT/.render/bgutil-ytdlp-pot-provider"

export XDG_CONFIG_HOME="$ROOT/.render/config"
AUTH_DIR="$XDG_CONFIG_HOME/clipperos"
COOKIES_PATH="$AUTH_DIR/cookies.txt"
AUTH_PREFS_PATH="$AUTH_DIR/auth_prefs.json"

if [ -z "${YOUTUBE_COOKIES_B64:-}" ]; then
  echo "[auth] ERROR: YOUTUBE_COOKIES_B64 is not configured." >&2
  exit 1
fi

mkdir -p "$AUTH_DIR"
if ! printf '%s' "$YOUTUBE_COOKIES_B64" | base64 --decode > "$COOKIES_PATH"; then
  rm -f "$COOKIES_PATH"
  echo "[auth] ERROR: YOUTUBE_COOKIES_B64 could not be decoded." >&2
  exit 1
fi
if [ ! -s "$COOKIES_PATH" ]; then
  rm -f "$COOKIES_PATH"
  echo "[auth] ERROR: YOUTUBE_COOKIES_B64 decoded to an empty file." >&2
  exit 1
fi
chmod 600 "$COOKIES_PATH"
printf '%s' '{"provider":"cookies_file"}' > "$AUTH_PREFS_PATH"
chmod 600 "$AUTH_PREFS_PATH"

if [ ! -f "$BGUTIL_DIR/server/build/main.js" ]; then
  echo "[bgutil] ERROR: provider build is missing at $BGUTIL_DIR/server/build/main.js" >&2
  echo "[bgutil] Run render-build.sh successfully before starting the service." >&2
  exit 1
fi

echo "[bgutil] installing/starting provider..."
BGUTIL_LOG="$ROOT/.render/bgutil-provider.log"
: > "$BGUTIL_LOG"

emit_bgutil_diagnostics() {
  while IFS= read -r line; do
    lower_line="${line,,}"
    case "$lower_line" in
      *"error"*|*"failed"*|*"exception"*|*"fatal"*)
        echo "[bgutil][diag] provider/startup error detected"
        ;;
      *"generating pot"*|*"/get_pot"*)
        echo "[bgutil][diag] PO-token request attempted"
        ;;
      *"potoken"*|*"generated integritytoken"*|*"retrieved a gvs po token"*)
        echo "[bgutil][diag] PO-token generation succeeded"
        ;;
    esac
  done
}

tail -n 0 -F "$BGUTIL_LOG" | emit_bgutil_diagnostics &
DIAG_PID=$!
node "$BGUTIL_DIR/server/build/main.js" --port 4416 > "$BGUTIL_LOG" 2>&1 &
PROVIDER_PID=$!

cleanup() {
  kill "$DIAG_PID" 2>/dev/null || true
  wait "$DIAG_PID" 2>/dev/null || true
  kill "$PROVIDER_PID" 2>/dev/null || true
  wait "$PROVIDER_PID" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

READY=false
for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:4416/ping >/dev/null 2>&1; then
    READY=true
    break
  fi
  if ! kill -0 "$PROVIDER_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done

if [ "$READY" != true ]; then
  echo "[bgutil] ERROR: provider failed health check at http://127.0.0.1:4416/ping" >&2
  echo "[bgutil][diag] 127.0.0.1:4416/ping failed; review preceding provider diagnostics." >&2
  exit 1
fi

echo "[bgutil] provider ready on 127.0.0.1:4416"
echo "[bgutil][diag] 127.0.0.1:4416/ping succeeded"
cd "$ROOT"
echo "[clipper] starting gunicorn..."
gunicorn --bind "0.0.0.0:${PORT:-10000}" --workers 1 production:application
