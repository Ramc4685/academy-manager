#!/usr/bin/env bash
# Serve the built OpenNext Worker in local workerd and fail on any 5xx.
# `next build`/`next start` (what e2e runs) cannot catch Workers-runtime
# breaks: 2026-10-29 Next 16.4.1 + OpenNext 1.20.6 built fine and 500'd
# every request in prod (Cloudflare 1101). Run from frontend/ after
# `opennextjs-cloudflare build`.
set -euo pipefail

PORT="${WORKER_SMOKE_PORT:-8799}"
HOST_HEADER="${WORKER_SMOKE_HOST:-blno-academy.courtmastr.com}"
PATHS="${WORKER_SMOKE_PATHS:-/ /login /admin /parent /coach}"
LOG="$(mktemp)"

pnpm exec wrangler dev --local --port "$PORT" >"$LOG" 2>&1 &
WRANGLER_PID=$!
trap 'pkill -P "$WRANGLER_PID" 2>/dev/null || true; kill "$WRANGLER_PID" 2>/dev/null || true; wait "$WRANGLER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://localhost:${PORT}/" && break
  if ! kill -0 "$WRANGLER_PID" 2>/dev/null; then
    cat "$LOG"
    echo "::error::wrangler dev exited before serving the Worker"
    exit 1
  fi
  sleep 2
done

failed=0
for path in $PATHS; do
  code="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: ${HOST_HEADER}" "http://localhost:${PORT}${path}")"
  echo "${path} -> ${code}"
  if [ "$code" = "000" ] || [ "$code" -ge 500 ]; then
    failed=1
  fi
done

if [ "$failed" -ne 0 ]; then
  grep -E "wrangler:error|Error" "$LOG" | head -20 || true
  echo "::error::Worker runtime smoke failed: a route returned 5xx (or no response) under workerd"
  exit 1
fi
echo "Worker runtime smoke passed."
