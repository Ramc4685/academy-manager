#!/usr/bin/env bash
#
# SaaS staging orchestrator — drives a local Docker stack that approximates
# the SaaS production deployment for testing.
#
# Quick start (one command):
#   make up               # build, start, seed, show URLs + creds
#
# Or step by step:
#   scripts/dev/saas_staging.sh up         # build + start the stack (production staging build)
#   scripts/dev/saas_staging.sh up-dev     # hot-reload mode: UI + backend reload on save
#   scripts/dev/saas_staging.sh seed       # seed tenant + Firebase test user
#   scripts/dev/saas_staging.sh status     # show containers + URLs + creds
#   scripts/dev/saas_staging.sh smoke      # run the SaaS readiness smoke
#   scripts/dev/saas_staging.sh audit blno # run launch-readiness audit for a tenant
#
# Rebuild individual services without restarting the whole stack:
#   scripts/dev/saas_staging.sh rebuild-ui  # rebuild + restart frontend only (staging build)
#   scripts/dev/saas_staging.sh rebuild-api # rebuild + restart backend only
#
# Custom test data:
#   scripts/dev/saas_staging.sh seed --slug blno --domain blno.localhost ...
#   scripts/dev/saas_staging.sh blno-seed   # seed BLno academy with full realistic data
#
# Lifecycle:
#   scripts/dev/saas_staging.sh logs <svc> # tail logs (backend|frontend|mongo|firebase-emulator)
#   scripts/dev/saas_staging.sh urls       # just print access URLs
#   scripts/dev/saas_staging.sh stripe-listen
#                                            # configure sandbox Stripe webhooks + forward events
#   scripts/dev/saas_staging.sh reset      # wipe test data, keep stack running
#   scripts/dev/saas_staging.sh down       # stop containers, keep volumes
#   scripts/dev/saas_staging.sh nuke       # stop + remove volumes (interactive confirm)
#
# Compose project is `saas-staging` to isolate from any other compose stack.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." &>/dev/null && pwd)"
cd "${REPO_ROOT}"

PROJECT_NAME="saas-staging"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.saas.yml)
COMPOSE=(docker compose -p "${PROJECT_NAME}" "${COMPOSE_FILES[@]}")
COMPOSE_DEV_FILES=(-f docker-compose.yml -f docker-compose.saas.yml -f docker-compose.saas-dev.yml)
COMPOSE_DEV=(docker compose -p "${PROJECT_NAME}" "${COMPOSE_DEV_FILES[@]}")

LOCAL_DIR="${REPO_ROOT}/.local"
ENV_FILE="${LOCAL_DIR}/saas-staging.env"
CREDS_FILE="${LOCAL_DIR}/saas-staging-credentials.json"
VENV_PYTHON="${VENV_PYTHON:-${REPO_ROOT}/backend/.venv/bin/python}"
SMOKE_SCRIPT="${REPO_ROOT}/scripts/smoke/saas_readiness_smoke.sh"
SEED_SCRIPT="${REPO_ROOT}/scripts/dev/seed_saas_staging.py"
BLNO_SEED_SCRIPT="${REPO_ROOT}/scripts/dev/seed_blno_staging.py"
STRIPE_WEBHOOK_URL="http://127.0.0.1:8001/api/v2/parent/webhooks/stripe"
STRIPE_WEBHOOK_EVENTS="checkout.session.completed,checkout.session.expired,payment_intent.succeeded,payment_intent.payment_failed,invoice.paid,invoice.payment_failed,charge.refunded,customer.subscription.updated,customer.subscription.deleted"

# Ports the stack binds. Used by pre-flight + status.
declare -a REQUIRED_PORTS=(3000 4000 8001 9099 27017)

# --- helpers ----------------------------------------------------------------

log()  { printf '\033[1;34m[saas-staging]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[saas-staging]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[saas-staging]\033[0m %s\n' "$*" >&2; exit 1; }

# Pre-flight checks for `up`. Fails fast with a clear message if the host
# can't run the stack — much friendlier than a 2-minute docker build crash.
preflight() {
  # Docker daemon reachable?
  if ! docker info >/dev/null 2>&1; then
    die "Docker daemon is not running. Start Docker Desktop, then retry."
  fi

  # Python venv exists?
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    die "backend/.venv not found. Create it with:
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -r backend/requirements.txt"
  fi

  # Ports free? (Allow ports occupied by THIS compose project — already-running stack.)
  local conflicting=()
  if command -v lsof >/dev/null 2>&1; then
    for port in "${REQUIRED_PORTS[@]}"; do
      local procs
      procs="$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
      if [[ -n "${procs}" ]]; then
        # Filter out our own containers (com.docker.* / Docker / containerd).
        if printf '%s\n' "${procs}" | grep -qvE '(com.docker|docker|containerd)'; then
          conflicting+=("${port}")
        fi
      fi
    done
  fi
  if (( ${#conflicting[@]} > 0 )); then
    warn "Ports already in use by non-Docker processes: ${conflicting[*]}"
    warn "Free them first, or your stack may fail to start."
    warn "  lsof -nP -iTCP -sTCP:LISTEN | awk '\$9 ~ /:(${REQUIRED_PORTS[*]})\$/'"
    warn "  (replace spaces in the awk pattern with |)"
    # Don't die — Docker may still be able to share the port with the existing user.
  fi
}

random_hex() { LC_ALL=C openssl rand -hex "${1:-32}"; }
random_password() { LC_ALL=C openssl rand -base64 36 | tr -d '\n=+/' | cut -c1-28; }

upsert_env_value() {
  local key="$1"
  local value="$2"
  mkdir -p "${LOCAL_DIR}"
  touch "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"

  local tmp
  tmp="$(mktemp)"
  awk -F= -v key="${key}" '$1 != key { print }' "${ENV_FILE}" > "${tmp}"
  printf '%s=%s\n' "${key}" "${value}" >> "${tmp}"
  mv "${tmp}" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
}

ensure_env_file() {
  if [[ -f "${ENV_FILE}" ]]; then
    return 0
  fi
  log "Generating fresh local SaaS staging secrets at ${ENV_FILE}"
  mkdir -p "${LOCAL_DIR}"
  umask 077
  {
    printf '# Auto-generated by scripts/dev/saas_staging.sh\n'
    printf '# Local Docker SaaS staging stack only. Never commit.\n'
    printf 'JWT_SECRET=%s\n' "$(random_hex 32)"
    printf 'ADMIN_PASSWORD=%s\n' "$(random_password)"
  } > "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
}

read_local_env_value() {
  local key="$1"
  local file line value
  for file in "${REPO_ROOT}/frontend/.env.local" "${REPO_ROOT}/frontend/.env" "${ENV_FILE}"; do
    [[ -f "${file}" ]] || continue
    line="$(awk -F= -v key="${key}" '$1 == key {print substr($0, index($0, "=") + 1)}' "${file}" | tail -n 1)"
    [[ -n "${line}" ]] || continue
    value="${line%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    if [[ -n "${value}" ]]; then
      printf '%s\n' "${value}"
      return 0
    fi
  done
  return 1
}

stripe_test_api_key() {
  if [[ -n "${STRIPE_API_KEY:-}" ]]; then
    case "${STRIPE_API_KEY}" in
      sk_test_*|rk_test_*) printf '%s\n' "${STRIPE_API_KEY}"; return 0 ;;
      *) die "STRIPE_API_KEY must be a Stripe test-mode secret or restricted key for local SaaS staging." ;;
    esac
  fi

  if ! command -v stripe >/dev/null 2>&1; then
    die "Stripe CLI is required. Install it with: brew install stripe/stripe-cli/stripe"
  fi

  local tmp key
  tmp="$(mktemp)"
  stripe config --list > "${tmp}"
  key="$(
    awk -F= '
      $1 ~ /^[[:space:]]*test_mode_api_key[[:space:]]*$/ {
        v=$2
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", v)
        gsub(/^'\''|'\''$/, "", v)
        gsub(/^"|"$/, "", v)
        print v
      }
    ' "${tmp}" | tail -n 1
  )"
  rm -f "${tmp}"
  [[ "${key}" == sk_test_* || "${key}" == rk_test_* ]] || die "Stripe CLI has no test-mode secret key. Run 'stripe login' or export STRIPE_API_KEY=sk_test_..."
  printf '%s\n' "${key}"
}

stripe_cli_webhook_secret() {
  local api_key="$1"
  local tmp secret
  tmp="$(mktemp)"
  stripe listen --api-key "${api_key}" --events "${STRIPE_WEBHOOK_EVENTS}" --print-secret > "${tmp}"
  secret="$(awk '/whsec_/ { print $NF }' "${tmp}" | tail -n 1)"
  rm -f "${tmp}"
  [[ "${secret}" == whsec_* ]] || die "Could not read Stripe CLI webhook signing secret."
  printf '%s\n' "${secret}"
}

firebase_api_key() {
  if [[ -n "${NEXT_PUBLIC_FIREBASE_API_KEY:-}" ]]; then
    printf '%s\n' "${NEXT_PUBLIC_FIREBASE_API_KEY}"
    return 0
  fi
  read_local_env_value NEXT_PUBLIC_FIREBASE_API_KEY
}

require_firebase_api_key() {
  local api_key
  api_key="$(firebase_api_key || true)"
  [[ -n "${api_key}" ]] || die "Missing NEXT_PUBLIC_FIREBASE_API_KEY. Add the real public Firebase web API key to frontend/.env.local or export it before running SaaS staging."
  printf '%s\n' "${api_key}"
}

# Wait up to <timeout>s for a URL to return 2xx.
wait_for_url() {
  local url="$1"
  local timeout_s="${2:-90}"
  local deadline=$(( $(date +%s) + timeout_s ))
  while (( $(date +%s) < deadline )); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

replay_migrations() {
  log "Replaying v2 migrations against SaaS staging Mongo..."
  PYTHONPATH="${REPO_ROOT}" \
  MONGO_URL="mongodb://127.0.0.1:27017" \
  DB_NAME="academy_manager_saas_staging" \
  "${VENV_PYTHON}" - <<'PY'
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

from backend.v2.migrations.runner import run_all_migrations


async def main() -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        replayed = await run_all_migrations(client[os.environ["DB_NAME"]])
        print(f"Replayed {len(replayed)} migrations")
    finally:
        client.close()


asyncio.run(main())
PY
}

launch_audit() {
  local academy_id="${1:-blno}"
  log "Running launch-readiness audit for academy_id=${academy_id}..."
  PYTHONPATH="${REPO_ROOT}" \
  APP_TENANCY_MODE=single_academy \
  ENABLE_PLATFORM_ROUTES=false \
  ENABLE_OWNER_ROLE=false \
  ENABLE_STUDENT_LOGIN=false \
  PRIMARY_ACADEMY_ID="${academy_id}" \
  "${VENV_PYTHON}" "${REPO_ROOT}/backend/scripts/launch_readiness_audit.py" \
    --mongo-url mongodb://127.0.0.1:27017 \
    --db-name academy_manager_saas_staging \
    --primary-academy-id "${academy_id}"
}

# --- commands ---------------------------------------------------------------

cmd_up() {
  ensure_env_file
  local api_key
  api_key="$(require_firebase_api_key)"
  preflight
  log "Building and starting stack (project=${PROJECT_NAME})..."
  NEXT_PUBLIC_FIREBASE_API_KEY="${api_key}" "${COMPOSE[@]}" up -d --build
  log "Waiting for backend health (up to 90s)..."
  if wait_for_url "http://127.0.0.1:8001/api/v2/healthz" 90; then
    log "Backend is healthy."
    log "Next:  scripts/dev/saas_staging.sh blno-seed   (seed BLno academy with realistic data)"
  else
    warn "Backend did not respond on http://127.0.0.1:8001/api/v2/healthz within 90s."
    warn "Inspect logs:  scripts/dev/saas_staging.sh logs backend"
    exit 1
  fi
}

cmd_stripe_listen() {
  ensure_env_file
  if ! command -v stripe >/dev/null 2>&1; then
    die "Stripe CLI is required. Install it with: brew install stripe/stripe-cli/stripe"
  fi

  log "Configuring Docker SaaS staging for Stripe sandbox webhooks..."
  local api_key webhook_secret
  api_key="$(stripe_test_api_key)"
  webhook_secret="$(stripe_cli_webhook_secret "${api_key}")"
  upsert_env_value STRIPE_API_KEY "${api_key}"
  upsert_env_value STRIPE_WEBHOOK_SECRET "${webhook_secret}"
  upsert_env_value V2_STRIPE_API_KEY "${api_key}"
  upsert_env_value V2_STRIPE_WEBHOOK_SECRET "${webhook_secret}"

  if "${COMPOSE[@]}" ps --status running --quiet backend 2>/dev/null | grep -q .; then
    log "Restarting backend so it picks up the matching Stripe webhook secret..."
    "${COMPOSE[@]}" up -d --no-deps --build backend
    wait_for_url "http://127.0.0.1:8001/api/v2/healthz" 60 || die "Backend did not become healthy after Stripe env update."
  else
    warn "Backend is not running yet. Start it with: scripts/dev/saas_staging.sh up"
  fi

  log "Forwarding Stripe sandbox events to ${STRIPE_WEBHOOK_URL}"
  log "Keep this process running while testing Checkout, autopay, portal, and invoice history."
  stripe listen \
    --api-key "${api_key}" \
    --forward-to "${STRIPE_WEBHOOK_URL}" \
    --events "${STRIPE_WEBHOOK_EVENTS}" \
    2>&1 | sed -E 's/whsec_[A-Za-z0-9_]+/[redacted-whsec]/g; s/(sk|rk)_(test|live)_[A-Za-z0-9_]+/[redacted-stripe-key]/g'
}

cmd_seed() {
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    die "backend/.venv not found. Run preflight check or create the venv first."
  fi
  log "Seeding tenant + Firebase emulator user..."
  "${VENV_PYTHON}" "${SEED_SCRIPT}" "$@"
  replay_migrations
}

cmd_blno_seed() {
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    die "backend/.venv not found. Run preflight check or create the venv first."
  fi
  log "Seeding BLno Badminton Academy (parents, students, sessions, invoice ledger, pathway)..."
  "${VENV_PYTHON}" "${BLNO_SEED_SCRIPT}" "$@"
  launch_audit blno
}

# Reset: wipe seeded test data + emulator users, but keep the stack running.
# Use this when you want a clean slate without paying the docker rebuild cost.
cmd_reset() {
  if ! "${COMPOSE[@]}" ps --status running --quiet 2>/dev/null | grep -q .; then
    die "Stack is not running. Use 'nuke' to clean state, or 'up' to start."
  fi
  warn "This will wipe ALL SaaS staging Mongo data + Firebase emulator users."
  warn "(The stack stays up; this is a fast in-place reset.)"
  read -r -p "Type 'reset' to confirm: " confirm
  [[ "${confirm}" == "reset" ]] || die "Aborted."

  log "Wiping Mongo SaaS staging DB..."
  "${COMPOSE[@]}" exec -T mongo mongosh academy_manager_saas_staging --quiet \
    --eval 'db.getCollectionNames().forEach(c => { if (!c.startsWith("system.")) db[c].drop(); })'

  log "Wiping Firebase emulator users..."
  # The emulator exposes an admin endpoint for project-wide account deletion.
  curl -fsS -X DELETE \
    "http://127.0.0.1:9099/emulator/v1/projects/academy-courtmastr/accounts" >/dev/null

  rm -f "${CREDS_FILE}"
  log "Reset complete. Re-seed with:  scripts/dev/saas_staging.sh seed"
}

# Status: show what's running + the URLs and login credentials at a glance.
cmd_status() {
  printf '\n  \033[1mSaaS staging — current status\033[0m\n\n'

  printf '  \033[1mContainers (project=%s):\033[0m\n' "${PROJECT_NAME}"
  if ! "${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Status}}' 2>/dev/null \
       | sed 's/^/    /' ; then
    printf '    (stack not running)\n'
    printf '    Run:  scripts/dev/saas_staging.sh up   (or: make saas-up)\n\n'
    return 0
  fi
  printf '\n'

  printf '  \033[1mAccess URLs:\033[0m\n'
  printf '    Frontend:              http://localhost:3000\n'
  printf '    Backend API:           http://127.0.0.1:8001\n'
  printf '    Backend health:        http://127.0.0.1:8001/api/v2/healthz\n'
  printf '    Firebase Emulator UI:  http://localhost:4000\n'
  printf '    Mongo:                 mongodb://127.0.0.1:27017/academy_manager_saas_staging\n'
  printf '\n'

  # If creds file exists, surface them.
  if [[ -f "${CREDS_FILE}" ]] && command -v "${VENV_PYTHON}" >/dev/null 2>&1; then
    printf '  \033[1mSeeded test user:\033[0m\n'
    "${VENV_PYTHON}" - <<PYEOF || true
import json
try:
    d = json.load(open("${CREDS_FILE}"))
    owners = d.get("owners")
    if isinstance(owners, dict) and owners:
        first = next(iter(owners.values()))
        print(f"    Admin:    {first.get('owner_email','(unknown)')} / {first.get('owner_password','(unknown)')}")
    else:
        print(f"    Admin:    {d.get('owner_email','(unknown)')} / {d.get('owner_password','(unknown)')}")
    sample_parent = d.get("sample_parent")
    if isinstance(sample_parent, dict):
        print(f"    Parent:   {sample_parent.get('email','(unknown)')} / {sample_parent.get('password','(unknown)')}")
    coaches = d.get("coaches")
    if isinstance(coaches, dict) and coaches:
        email, password = next(iter(coaches.items()))
        print(f"    Coach:    {email} / {password}")
    print(f"    File:     ${CREDS_FILE}")
except Exception as e:
    print(f"    (could not read creds: {e})")
PYEOF
    printf '\n'
  else
    printf '  \033[1mSeeded test user:\033[0m  (no credentials file yet — run: scripts/dev/saas_staging.sh seed)\n\n'
  fi

  # Tenant-host pointer (for browser-based subdomain testing).
  if command -v "${VENV_PYTHON}" >/dev/null 2>&1; then
    local tenants
    tenants="$("${VENV_PYTHON}" - <<'PYEOF' 2>/dev/null || true
from pymongo import MongoClient
try:
    db = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=2000).academy_manager_saas_staging
    for a in db.academies.find({}, {"_id":0,"slug":1,"primary_domain":1,"display_name":1}):
        print(f"    {a.get('slug','?'):16s} {a.get('primary_domain','?'):28s} {a.get('display_name','')}")
except Exception:
    pass
PYEOF
)"
    if [[ -n "${tenants}" ]]; then
      printf '  \033[1mSeeded tenants:\033[0m\n%s\n\n' "${tenants}"
      printf '    Browser:  http://<primary_domain>:3000/login\n'
      printf '    (e.g.     http://acme.localhost:3000/login)\n\n'
    fi
  fi

  printf '  Run smoke:  scripts/dev/saas_staging.sh smoke   (or: make saas-test)\n\n'
}

# urls: minimal "where do I click?" output — used by other scripts.
cmd_urls() {
  cat <<EOF
http://localhost:3000              # Frontend (any tenant via Host header)
http://acme.localhost:3000         # Frontend, scoped to acme tenant
http://127.0.0.1:8001              # Backend API root
http://127.0.0.1:8001/api/v2/healthz   # Backend health check
http://localhost:4000              # Firebase Emulator UI
mongodb://127.0.0.1:27017          # Mongo (db: academy_manager_saas_staging)
EOF
}

cmd_smoke() {
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    die "backend/.venv not found."
  fi
  [[ -x "${SMOKE_SCRIPT}" ]] || die "Smoke script not found: ${SMOKE_SCRIPT}"

  log "Generating fresh smoke env from seed..."
  local seed_json
  seed_json="$("${VENV_PYTHON}" "${SEED_SCRIPT}" --json "$@")"
  replay_migrations

  local api_url frontend_url tenant_frontend_url tenant_host hdr_name hdr_val id_token
  api_url="$(printf '%s' "${seed_json}"      | "${VENV_PYTHON}" -c 'import json,sys;print(json.load(sys.stdin)["api_url"])')"
  frontend_url="$(printf '%s' "${seed_json}" | "${VENV_PYTHON}" -c 'import json,sys;print(json.load(sys.stdin)["frontend_url"])')"
  tenant_frontend_url="$(printf '%s' "${seed_json}" | "${VENV_PYTHON}" -c 'import json,sys;print(json.load(sys.stdin).get("tenant_frontend_url",""))')"
  tenant_host="$(printf '%s' "${seed_json}"  | "${VENV_PYTHON}" -c 'import json,sys;print(json.load(sys.stdin)["unknown_host_for_smoke"])')"
  hdr_name="$(printf '%s' "${seed_json}"     | "${VENV_PYTHON}" -c 'import json,sys;print(json.load(sys.stdin)["internal_tenant_header_name"])')"
  hdr_val="$(printf '%s' "${seed_json}"      | "${VENV_PYTHON}" -c 'import json,sys;print(json.load(sys.stdin)["academy_id"])')"
  id_token="$(printf '%s' "${seed_json}"     | "${VENV_PYTHON}" -c 'import json,sys;print(json.load(sys.stdin)["id_token"])')"

  log "Running SaaS readiness smoke against ${api_url}..."
  API_URL="${api_url}" \
  FRONTEND_URL="${frontend_url}" \
  TENANT_FRONTEND_URL="${tenant_frontend_url}" \
  TENANT_HOST="${tenant_host}" \
  INTERNAL_TENANT_HEADER_NAME="${hdr_name}" \
  INTERNAL_TENANT_HEADER_VALUE="${hdr_val}" \
  AUTH_TOKEN="${id_token}" \
    "${SMOKE_SCRIPT}"
}

cmd_audit() {
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    die "backend/.venv not found."
  fi
  local academy_id="${1:-blno}"
  launch_audit "${academy_id}"
}

cmd_token() { cmd_seed "$@"; }

cmd_logs() {
  local service="${1:-backend}"
  shift || true
  "${COMPOSE[@]}" logs -f --tail=200 "${service}" "$@"
}

cmd_ps() { "${COMPOSE[@]}" ps; }

cmd_down() {
  log "Stopping stack (keeping volumes)..."
  "${COMPOSE[@]}" down
  log "Stopped. Mongo data + emulator state preserved."
  log "Restart with:  scripts/dev/saas_staging.sh up   (or: make saas-up)"
}

cmd_nuke() {
  warn "This will remove all SaaS-staging containers AND volumes (Mongo data, emulator state)."
  read -r -p "Type 'nuke' to confirm: " confirm
  [[ "${confirm}" == "nuke" ]] || die "Aborted."
  "${COMPOSE[@]}" down -v
  rm -f "${ENV_FILE}" "${CREDS_FILE}"
  rm -f "${LOCAL_DIR}/saas-tunnel-urls.env" "${LOCAL_DIR}/saas-tunnel-cors.yml"
  log "Nuked. Run 'up' to rebuild from a clean slate (or: make up)."
}

cmd_up_dev() {
  ensure_env_file
  local api_key
  api_key="$(require_firebase_api_key)"
  preflight
  log "Starting stack in hot-reload dev mode (project=${PROJECT_NAME})..."
  NEXT_PUBLIC_FIREBASE_API_KEY="${api_key}" "${COMPOSE_DEV[@]}" up -d --build
  log "Waiting for backend health (up to 90s)..."
  if wait_for_url "http://127.0.0.1:8001/api/v2/healthz" 90; then
    log "Stack up in hot-reload mode."
    log "  Frontend  → save a file, browser refreshes automatically (next dev + polling)."
    log "  Backend   → save a .py file, uvicorn reloads automatically."
    log "Next:  scripts/dev/saas_staging.sh blno-seed   (seed BLno academy with realistic data)"
  else
    warn "Backend did not respond on http://127.0.0.1:8001/api/v2/healthz within 90s."
    warn "Inspect logs:  scripts/dev/saas_staging.sh logs backend"
    exit 1
  fi
}

cmd_rebuild_ui() {
  log "Rebuilding frontend (deps layer cached if pnpm-lock.yaml unchanged)..."
  "${COMPOSE[@]}" up -d --no-deps --build frontend
  log "Frontend rebuilt and restarted at http://localhost:3000"
}

cmd_rebuild_api() {
  log "Rebuilding backend (deps layer cached if requirements.txt unchanged)..."
  "${COMPOSE[@]}" up -d --no-deps --build backend
  if wait_for_url "http://127.0.0.1:8001/api/v2/healthz" 60; then
    log "Backend rebuilt and healthy."
  else
    warn "Backend did not respond within 60s. Check: scripts/dev/saas_staging.sh logs backend"
  fi
}

usage() {
  sed -n '3,35p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

main() {
  local cmd="${1:-}"
  shift || true
  case "${cmd}" in
    up)          cmd_up "$@" ;;
    up-dev)      cmd_up_dev "$@" ;;
    rebuild-ui)  cmd_rebuild_ui "$@" ;;
    rebuild-api) cmd_rebuild_api "$@" ;;
    seed)        cmd_seed "$@" ;;
    blno-seed)   cmd_blno_seed "$@" ;;
    reset)       cmd_reset "$@" ;;
    status) cmd_status "$@" ;;
    urls)   cmd_urls "$@" ;;
    token)  cmd_token "$@" ;;
    smoke)  cmd_smoke "$@" ;;
    audit)  cmd_audit "$@" ;;
    stripe-listen) cmd_stripe_listen "$@" ;;
    logs)   cmd_logs "$@" ;;
    ps)     cmd_ps "$@" ;;
    down)   cmd_down "$@" ;;
    nuke)   cmd_nuke "$@" ;;
    ""|-h|--help|help) usage ;;
    *) usage; die "Unknown command: ${cmd}" ;;
  esac
}

main "$@"
