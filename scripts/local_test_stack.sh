#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ACADEMY_LOCAL_RUN_DIR:-/tmp/academy-manager-local}"
PID_DIR="${RUN_DIR}/pids"
LOG_DIR="${RUN_DIR}/logs"

MONGO_HOST="${MONGO_HOST:-127.0.0.1}"
MONGO_PORT="${MONGO_PORT:-27017}"
MONGO_URL="${MONGO_URL:-mongodb://${MONGO_HOST}:${MONGO_PORT}}"
MONGO_DBPATH="${MONGO_DBPATH:-${RUN_DIR}/mongo-data}"
DB_NAME="${DB_NAME:-academy_manager_local}"

FIREBASE_PROJECT_ID="${FIREBASE_PROJECT_ID:-academy-courtmastr}"
FIREBASE_AUTH_HOST="${FIREBASE_AUTH_HOST:-127.0.0.1}"
FIREBASE_AUTH_PORT="${FIREBASE_AUTH_PORT:-9099}"
FIREBASE_UI_PORT="${FIREBASE_UI_PORT:-4000}"
FIREBASE_AUTH_EMULATOR_HOST="${FIREBASE_AUTH_EMULATOR_HOST:-${FIREBASE_AUTH_HOST}:${FIREBASE_AUTH_PORT}}"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8001}"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"

FRONTEND_HOST="${FRONTEND_HOST:-localhost}"
FRONTEND_PORT="${FRONTEND_PORT:-3001}"
FRONTEND_URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}"

mkdir -p "${PID_DIR}" "${LOG_DIR}"

usage() {
  cat <<EOF
Usage: scripts/local_test_stack.sh <command>

Commands:
  fresh        FULL RESET: stop → start everything → seed demo data. Use this to start testing.
  all          Start infra + app (skips already-running services), then smoke check.
  status       Show local Mongo/Firebase/backend/frontend status.
  infra        Start local MongoDB and Firebase Auth emulator if missing.
  app          Start backend and frontend if missing.
  smoke        Check local health endpoints and expected ports.
  seed         Drop and re-seed demo data into local MongoDB (destructive).
  test         Run backend v2 tests and frontend typecheck.
  logs         Print log file paths and recent lines.
  stop         Stop only processes started by this script.
EOF
}

log() {
  printf '\n==> %s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

port_pids() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | paste -sd, - || true
}

has_listener() {
  [ -n "$(port_pids "$1")" ]
}

print_port() {
  label="$1"
  port="$2"
  pids="$(port_pids "${port}")"
  if [ -n "${pids}" ]; then
    printf '%-24s RUNNING port=%s pid=%s\n' "${label}" "${port}" "${pids}"
  else
    printf '%-24s stopped port=%s\n' "${label}" "${port}"
  fi
}

wait_for_port_free() {
  label="$1"
  port="$2"
  timeout="${3:-15}"
  started_at="$(date +%s)"
  while has_listener "${port}"; do
    if [ "$(( $(date +%s) - started_at ))" -ge "${timeout}" ]; then
      printf 'WARN: %s port %s did not free within %ss — continuing anyway\n' "${label}" "${port}" "${timeout}" >&2
      return 0
    fi
    sleep 1
  done
}

wait_for_port() {
  label="$1"
  port="$2"
  timeout="${3:-30}"
  started_at="$(date +%s)"
  while ! has_listener "${port}"; do
    if [ "$(( $(date +%s) - started_at ))" -ge "${timeout}" ]; then
      printf 'WARN: %s did not open port %s within %ss\n' "${label}" "${port}" "${timeout}" >&2
      return 1
    fi
    sleep 1
  done
}

wait_for_url() {
  label="$1"
  url="$2"
  timeout="${3:-45}"
  started_at="$(date +%s)"
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if [ "$(( $(date +%s) - started_at ))" -ge "${timeout}" ]; then
      printf 'WARN: %s did not respond at %s within %ss\n' "${label}" "${url}" "${timeout}" >&2
      return 1
    fi
    sleep 1
  done
}

write_pid() {
  printf '%s\n' "$2" > "${PID_DIR}/$1.pid"
}

collect_tree() {
  # Print pid plus all live descendants, depth-first. Must run BEFORE any kill:
  # once a parent dies its children reparent and pgrep -P can no longer find them.
  pid_to_walk="$1"
  for child in $(pgrep -P "${pid_to_walk}" 2>/dev/null || true); do
    collect_tree "${child}"
  done
  printf '%s\n' "${pid_to_walk}"
}

kill_tree() {
  root_pid="$1"
  tree_pids="$(collect_tree "${root_pid}")"
  # Services are spawned as process-group leaders (set -m), so -PGID reaches
  # children even if the tree walk missed them. Stacks started before this
  # change have no dedicated group; the per-pid kills cover those.
  kill -TERM -- "-${root_pid}" 2>/dev/null || true
  # shellcheck disable=SC2086
  kill -TERM ${tree_pids} 2>/dev/null || true
  deadline="$(( $(date +%s) + 8 ))"
  while [ "$(date +%s)" -lt "${deadline}" ]; do
    survivors=""
    for p in ${tree_pids}; do
      if kill -0 "${p}" 2>/dev/null; then
        survivors="${survivors} ${p}"
      fi
    done
    if [ -z "${survivors}" ]; then
      return 0
    fi
    sleep 1
  done
  kill -KILL -- "-${root_pid}" 2>/dev/null || true
  # shellcheck disable=SC2086
  kill -KILL ${tree_pids} 2>/dev/null || true
}

read_frontend_env() {
  key="$1"
  for file in "${ROOT_DIR}/frontend/.env.local" "${ROOT_DIR}/frontend/.env" "${ROOT_DIR}/frontend/.env.example"; do
    [ -f "${file}" ] || continue
    value="$(awk -F= -v key="${key}" '$1 == key {print substr($0, index($0, "=") + 1)}' "${file}" | tail -n 1)"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    if [ -n "${value}" ]; then
      printf '%s\n' "${value}"
      return 0
    fi
  done
  return 1
}

firebase_api_key() {
  if is_valid_firebase_api_key "${NEXT_PUBLIC_FIREBASE_API_KEY:-}"; then
    printf '%s\n' "${NEXT_PUBLIC_FIREBASE_API_KEY}"
    return 0
  fi
  value="$(read_frontend_env NEXT_PUBLIC_FIREBASE_API_KEY || true)"
  if is_valid_firebase_api_key "${value}"; then
    printf '%s\n' "${value}"
    return 0
  fi
  value="$(read_frontend_env REACT_APP_FIREBASE_API_KEY || true)"
  if is_valid_firebase_api_key "${value}"; then
    printf '%s\n' "${value}"
    return 0
  fi
  return 1
}

is_valid_firebase_api_key() {
  key="${1:-}"
  [ "${key}" != "dummy" ] || return 1
  [ "${#key}" -ge 30 ] || return 1
  case "${key}" in
    AIza*) return 0 ;;
    *) return 1 ;;
  esac
}

bootstrap_env_local() {
  env_local="${ROOT_DIR}/frontend/.env.local"
  [ -f "${env_local}" ] && return 0
  api_key="$(firebase_api_key || true)"
  [ -n "${api_key}" ] || return 0
  sender_id="$(read_frontend_env NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID || read_frontend_env REACT_APP_FIREBASE_MESSAGING_SENDER_ID || true)"
  app_id="$(read_frontend_env NEXT_PUBLIC_FIREBASE_APP_ID || read_frontend_env REACT_APP_FIREBASE_APP_ID || true)"
  measurement_id="$(read_frontend_env NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID || read_frontend_env REACT_APP_FIREBASE_MEASUREMENT_ID || true)"
  log "Creating frontend/.env.local (one-time bootstrap)"
  cat >"${env_local}" <<EOF
BFF_API_ORIGIN=${BACKEND_URL}
NEXT_PUBLIC_API_BASE=/api/v2
NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW=${NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW:-1}
NEXT_PUBLIC_FIREBASE_API_KEY=${api_key}
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=${FIREBASE_PROJECT_ID}.firebaseapp.com
NEXT_PUBLIC_FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=${FIREBASE_PROJECT_ID}.firebasestorage.app
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=${sender_id}
NEXT_PUBLIC_FIREBASE_APP_ID=${app_id}
NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=${measurement_id}
NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST=http://${FIREBASE_AUTH_EMULATOR_HOST}
EOF
}

start_mongo() {
  if has_listener "${MONGO_PORT}"; then
    log "MongoDB already listening on ${MONGO_HOST}:${MONGO_PORT}"
    return 0
  fi
  command -v mongod >/dev/null 2>&1 || die "mongod is not installed or not on PATH"
  log "Starting MongoDB on ${MONGO_HOST}:${MONGO_PORT}"
  mkdir -p "${MONGO_DBPATH}"
  # Watchdog subshell: restarts mongod if it exits unexpectedly.
  # SIGTERM (sent by stop_started) kills the mongod child and exits the loop cleanly.
  # set -m puts the job in its own process group so stop can kill -- -PGID.
  set -m
  (
    _mongod_pid=""
    trap 'kill "${_mongod_pid:-}" 2>/dev/null; exit 0' TERM INT
    while true; do
      mongod --dbpath "${MONGO_DBPATH}" --bind_ip "${MONGO_HOST}" --port "${MONGO_PORT}" \
        >>"${LOG_DIR}/mongo.log" 2>&1 &
      _mongod_pid=$!
      wait "${_mongod_pid}" || true
      printf '[mongo-watchdog] mongod pid=%s exited, restarting in 2s\n' "${_mongod_pid}" \
        >>"${LOG_DIR}/mongo.log"
      sleep 2
    done
  ) &
  write_pid mongo "$!"
  set +m
  wait_for_port "MongoDB" "${MONGO_PORT}" 30 || { tail -n 80 "${LOG_DIR}/mongo.log" >&2 || true; exit 1; }
}

start_firebase() {
  if has_listener "${FIREBASE_AUTH_PORT}"; then
    log "Firebase Auth emulator already listening on ${FIREBASE_AUTH_HOST}:${FIREBASE_AUTH_PORT}"
    return 0
  fi
  command -v firebase >/dev/null 2>&1 || die "firebase CLI is not installed or not on PATH"
  firebase_config="${RUN_DIR}/firebase.local.json"
  cat >"${firebase_config}" <<EOF
{"emulators":{"auth":{"host":"${FIREBASE_AUTH_HOST}","port":${FIREBASE_AUTH_PORT}},"ui":{"enabled":true,"host":"127.0.0.1","port":${FIREBASE_UI_PORT}},"singleProjectMode":true}}
EOF
  log "Starting Firebase Auth emulator for ${FIREBASE_PROJECT_ID}"
  set -m
  (cd "${ROOT_DIR}" && nohup firebase emulators:start --config "${firebase_config}" --only auth --project "${FIREBASE_PROJECT_ID}") >"${LOG_DIR}/firebase.log" 2>&1 &
  write_pid firebase "$!"
  set +m
  wait_for_port "Firebase Auth emulator" "${FIREBASE_AUTH_PORT}" 45 || { tail -n 120 "${LOG_DIR}/firebase.log" >&2 || true; exit 1; }
}

start_backend() {
  if has_listener "${BACKEND_PORT}"; then
    log "Backend already listening on ${BACKEND_HOST}:${BACKEND_PORT}"
    return 0
  fi
  [ -x "${ROOT_DIR}/backend/.venv/bin/python" ] || die "backend/.venv is missing"
  log "Starting backend on ${BACKEND_URL}"
  set -m
  (
    cd "${ROOT_DIR}/backend"
    # shellcheck disable=SC1091
    . .venv/bin/activate
    nohup env APP_ENV=development EMAIL_DELIVERY_MODE=disabled MONGO_URL="${MONGO_URL}" DB_NAME="${DB_NAME}" FIREBASE_AUTH_ENABLED=true FIREBASE_PROJECT_ID="${FIREBASE_PROJECT_ID}" FIREBASE_AUTH_EMULATOR_HOST="${FIREBASE_AUTH_EMULATOR_HOST}" FRONTEND_URL="${FRONTEND_URL}" CORS_ORIGINS="${FRONTEND_URL},http://127.0.0.1:${FRONTEND_PORT}" COOKIE_SECURE=false V2_ALLOWED_INTERNAL_TENANT_HEADER=x-academy-id V2_DEFAULT_ACADEMY_ID=blno PYTHONPATH="${ROOT_DIR}" uvicorn backend.v2.main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --reload
  ) >"${LOG_DIR}/backend.log" 2>&1 &
  write_pid backend "$!"
  set +m
  wait_for_url "Backend health" "${BACKEND_URL}/api/v2/healthz" 60 || { tail -n 120 "${LOG_DIR}/backend.log" >&2 || true; exit 1; }
}

start_frontend() {
  bootstrap_env_local
  if has_listener "${FRONTEND_PORT}"; then
    log "Frontend already listening on ${FRONTEND_HOST}:${FRONTEND_PORT}"
    return 0
  fi
  command -v pnpm >/dev/null 2>&1 || die "pnpm is not installed or not on PATH"
  api_key="$(firebase_api_key || true)"
  [ -n "${api_key}" ] || die "Missing NEXT_PUBLIC_FIREBASE_API_KEY. Add it to frontend/.env.local or export it."
  log "Starting frontend on ${FRONTEND_URL}"
  frontend_cmd="cd '${ROOT_DIR}/frontend' && env BFF_API_ORIGIN='${BACKEND_URL}' NEXT_PUBLIC_API_BASE=/api/v2 NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW='${NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW:-1}' NEXT_PUBLIC_FIREBASE_API_KEY='${api_key}' NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN='${NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN:-${FIREBASE_PROJECT_ID}.firebaseapp.com}' NEXT_PUBLIC_FIREBASE_PROJECT_ID='${NEXT_PUBLIC_FIREBASE_PROJECT_ID:-${FIREBASE_PROJECT_ID}}' NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET='${NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET:-${FIREBASE_PROJECT_ID}.firebasestorage.app}' NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID='${NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID:-953230788846}' NEXT_PUBLIC_FIREBASE_APP_ID='${NEXT_PUBLIC_FIREBASE_APP_ID:-1:953230788846:web:1f2819c11418ecf5860bff}' NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID='${NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID:-G-Z6GS6WRZY8}' NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST='${NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST:-http://${FIREBASE_AUTH_EMULATOR_HOST}}' NEXT_PUBLIC_ACADEMY_SLUG=blno PORT='${FRONTEND_PORT}' pnpm dev >'${LOG_DIR}/frontend.log' 2>&1"
  if command -v screen >/dev/null 2>&1; then
    screen -S academy-frontend -X quit >/dev/null 2>&1 || true
    screen -dmS academy-frontend bash -lc "${frontend_cmd}"
    screen_pid="$( (screen -ls || true) | awk '/academy-frontend/ {split($1, parts, "."); print parts[1]; exit}')"
    if [ -n "${screen_pid}" ]; then
      write_pid frontend "${screen_pid}"
    fi
  else
    set -m
    nohup bash -lc "${frontend_cmd}" >/dev/null 2>&1 &
    write_pid frontend "$!"
    set +m
  fi
  wait_for_url "Frontend BFF proxy" "${FRONTEND_URL}/api/v2/healthz" 90 || { tail -n 120 "${LOG_DIR}/frontend.log" >&2 || true; exit 1; }
}

status() {
  print_port "MongoDB" "${MONGO_PORT}"
  print_port "Firebase Auth" "${FIREBASE_AUTH_PORT}"
  print_port "Firebase UI" "${FIREBASE_UI_PORT}"
  print_port "Backend API" "${BACKEND_PORT}"
  print_port "Frontend" "${FRONTEND_PORT}"
  printf '\nLogs: %s\n' "${LOG_DIR}"
}

smoke() {
  log "Checking local ports"
  status
  log "Checking backend health"
  curl -fsS "${BACKEND_URL}/api/v2/healthz"; printf '\n'
  log "Checking frontend BFF proxy"
  curl -fsS "${FRONTEND_URL}/api/v2/healthz"; printf '\n'
}

seed() {
  [ -f "${ROOT_DIR}/backend/scripts/seed_local.py" ] || die "Missing backend/scripts/seed_local.py"
  [ -f "${ROOT_DIR}/scripts/dev/seed_badminton_pathway.py" ] || die "Missing scripts/dev/seed_badminton_pathway.py"
  [ -x "${ROOT_DIR}/backend/.venv/bin/python" ] || die "backend/.venv is missing"
  log "Seeding ${DB_NAME}"
  (cd "${ROOT_DIR}" && env MONGO_URL="${MONGO_URL}" DB_NAME="${DB_NAME}" FIREBASE_AUTH_ENABLED=true FIREBASE_PROJECT_ID="${FIREBASE_PROJECT_ID}" FIREBASE_AUTH_EMULATOR_HOST="${FIREBASE_AUTH_EMULATOR_HOST}" backend/.venv/bin/python backend/scripts/seed_local.py)
  log "Seeding badminton skill pathway"
  (cd "${ROOT_DIR}" && env PYTHONPATH="${ROOT_DIR}" MONGO_URL="${MONGO_URL}" DB_NAME="${DB_NAME}" ACADEMY_ID=blno backend/.venv/bin/python scripts/dev/seed_badminton_pathway.py)
  log "Backfilling student pathway placements"
  (cd "${ROOT_DIR}" && env PYTHONPATH="${ROOT_DIR}" MONGO_URL="${MONGO_URL}" DB_NAME="${DB_NAME}" backend/.venv/bin/python scripts/dev/backfill_student_pathway_placements.py --academy-id blno --apply)
  log "Reapplying v2 migrations after seed reset"
  (cd "${ROOT_DIR}" && env PYTHONPATH="${ROOT_DIR}" MONGO_URL="${MONGO_URL}" DB_NAME="${DB_NAME}" backend/.venv/bin/python - <<'PY'
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

from backend.v2.migrations.runner import run_all_migrations


async def main() -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        db = client[os.environ["DB_NAME"]]
        replayed = await run_all_migrations(db)
        print(f"Replayed {len(replayed)} migrations")
    finally:
        client.close()


asyncio.run(main())
PY
  )
}

run_tests() {
  log "Running backend v2 tests"
  (
    cd "${ROOT_DIR}/backend"
    # shellcheck disable=SC1091
    . .venv/bin/activate
    python -m pytest v2/tests -q
  )
  log "Running frontend typecheck"
  (cd "${ROOT_DIR}/frontend" && pnpm typecheck)
}

logs() {
  printf 'Log directory: %s\n' "${LOG_DIR}"
  for name in mongo firebase backend frontend; do
    file="${LOG_DIR}/${name}.log"
    [ -f "${file}" ] || continue
    printf '\n--- %s ---\n' "${file}"
    tail -n 40 "${file}" || true
  done
}

stop_started() {
  log "Stopping processes started by this script"
  stopped_any=0
  for name in frontend backend firebase mongo; do
    pid_file="${PID_DIR}/${name}.pid"
    if [ "${name}" = "frontend" ] && command -v screen >/dev/null 2>&1; then
      # Frontend may run inside a screen session; quitting it kills the whole session tree.
      screen -S academy-frontend -X quit >/dev/null 2>&1 || true
    fi
    if [ ! -f "${pid_file}" ]; then
      printf '%-10s no pid file\n' "${name}"
      continue
    fi
    pid="$(cat "${pid_file}")"
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill_tree "${pid}"
      stopped_any=1
      printf '%-10s stopped pid=%s (and descendants)\n' "${name}" "${pid}"
    else
      # Leader already gone, but orphaned children may still hold its process group.
      if kill -TERM -- "-${pid}" 2>/dev/null; then
        stopped_any=1
      fi
      printf '%-10s pid not running (%s)\n' "${name}" "${pid}"
    fi
    rm -f "${pid_file}"
  done
  verify_ports_free "${stopped_any}"
}

verify_ports_free() {
  # Grace period only matters if we actually signalled something.
  grace="$([ "${1:-0}" -eq 1 ] && echo 5 || echo 0)"
  log "Verifying stack ports are free"
  leftover=0
  for spec in "MongoDB:${MONGO_PORT}" "Firebase Auth:${FIREBASE_AUTH_PORT}" "Backend API:${BACKEND_PORT}" "Frontend:${FRONTEND_PORT}"; do
    label="${spec%%:*}"
    port="${spec##*:}"
    if [ "${grace}" -gt 0 ]; then
      wait_for_port_free "${label}" "${port}" "${grace}" 2>/dev/null
    fi
    if has_listener "${port}"; then
      leftover=1
      printf 'WARN: %s port %s still has listeners:\n' "${label}" "${port}" >&2
      lsof -nP -iTCP:"${port}" -sTCP:LISTEN >&2 2>/dev/null || true
    else
      printf '%-24s port %s free\n' "${label}" "${port}"
    fi
  done
  if [ "${leftover}" -ne 0 ]; then
    printf '\nWARN: some ports are still in use. If a Docker stack owns them this is expected;\n' >&2
    printf 'otherwise stray local processes may shadow other stacks — kill the PIDs above.\n' >&2
  fi
}

case "${1:-all}" in
  fresh) stop_started; wait_for_port_free "MongoDB" "${MONGO_PORT}"; wait_for_port_free "Firebase Auth" "${FIREBASE_AUTH_PORT}"; wait_for_port_free "Firebase UI" "${FIREBASE_UI_PORT}"; wait_for_port_free "Backend" "${BACKEND_PORT}"; wait_for_port_free "Frontend" "${FRONTEND_PORT}"; start_mongo; start_firebase; start_backend; start_frontend; seed; smoke ;;
  status) status ;;
  infra) start_mongo; start_firebase; status ;;
  app) start_backend; start_frontend; status ;;
  all) start_mongo; start_firebase; start_backend; start_frontend; smoke ;;
  smoke) smoke ;;
  seed) seed ;;
  test) run_tests ;;
  logs) logs ;;
  stop) stop_started ;;
  help|-h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
