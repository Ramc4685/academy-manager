#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-https://api.academy.courtmastr.com}"
FRONTEND_URL="${FRONTEND_URL:-https://academy.courtmastr.com}"
EXPECTED_FIREBASE_PROJECT_ID="${EXPECTED_FIREBASE_PROJECT_ID:-academy-courtmastr}"
# Space-separated extra tenant origins served by the same Worker and API.
TENANT_FRONTEND_URLS="${TENANT_FRONTEND_URLS:-}"
CURL_RETRY_ATTEMPTS="${CURL_RETRY_ATTEMPTS:-6}"
CURL_RETRY_DELAY_SECONDS="${CURL_RETRY_DELAY_SECONDS:-5}"
CURL_CONNECT_TIMEOUT_SECONDS="${CURL_CONNECT_TIMEOUT_SECONDS:-10}"
CURL_MAX_TIME_SECONDS="${CURL_MAX_TIME_SECONDS:-60}"
CHUNK_SCAN_ATTEMPTS="${CHUNK_SCAN_ATTEMPTS:-6}"
CHUNK_SCAN_DELAY_SECONDS="${CHUNK_SCAN_DELAY_SECONDS:-10}"

curl_smoke() {
  curl -fsS \
    --retry "${CURL_RETRY_ATTEMPTS}" \
    --retry-delay "${CURL_RETRY_DELAY_SECONDS}" \
    --retry-all-errors \
    --connect-timeout "${CURL_CONNECT_TIMEOUT_SECONDS}" \
    --max-time "${CURL_MAX_TIME_SECONDS}" \
    "$@"
}

curl_smoke_status() {
  curl -sS \
    --retry "${CURL_RETRY_ATTEMPTS}" \
    --retry-delay "${CURL_RETRY_DELAY_SECONDS}" \
    --retry-all-errors \
    --connect-timeout "${CURL_CONNECT_TIMEOUT_SECONDS}" \
    --max-time "${CURL_MAX_TIME_SECONDS}" \
    "$@"
}

echo "Checking API health..."
health_body="$(curl_smoke "${API_URL}/api/v2/healthz")"
if ! grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' <<<"${health_body}"; then
  echo "API health check failed: expected \"status\":\"ok\" from ${API_URL}/api/v2/healthz" >&2
  exit 1
fi

check_cors_for_origin() {
  local origin="$1"
  echo "Checking API CORS preflight for ${origin}..."
  local cors_headers allow_origin allow_origin_lower origin_lower
  cors_headers="$(curl_smoke -D - -o /dev/null -X OPTIONS \
    -H "Origin: ${origin}" \
    -H "Access-Control-Request-Method: GET" \
    "${API_URL}/api/v2/me")"
  allow_origin="$(awk 'tolower($0) ~ /^access-control-allow-origin:/ {
    sub(/^[^:]*:[[:space:]]*/, "")
    sub(/\r$/, "")
    print
    exit
  }' <<<"${cors_headers}")"
  allow_origin_lower="$(printf '%s' "${allow_origin}" | tr '[:upper:]' '[:lower:]')"
  origin_lower="$(printf '%s' "${origin}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${allow_origin_lower}" != "${origin_lower}" ]]; then
    echo "CORS preflight failed: expected access-control-allow-origin ${origin}, got ${allow_origin:-<missing>}" >&2
    exit 1
  fi
}

check_frontend_origin() {
  local origin="$1"
  echo "Checking frontend ${origin}..."
  local headers html bff
  headers="$(curl_smoke -I "${origin}")"
  if ! grep -qi '^content-type:.*text/html' <<<"${headers}"; then
    echo "Frontend check failed: expected HTML response from ${origin}" >&2
    exit 1
  fi
  html="$(curl_smoke "${origin}")"
  if ! grep -qiE 'CourtMastr|Academy Manager|badminton|Run your' <<<"${html}"; then
    echo "Frontend check failed: expected CourtMastr/Academy content from ${origin}" >&2
    exit 1
  fi
  echo "Checking frontend BFF proxy for ${origin}..."
  bff="$(curl_smoke "${origin}/api/v2/healthz")"
  if ! grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' <<<"${bff}"; then
    echo "Frontend BFF proxy check failed: expected \"status\":\"ok\" from ${origin}/api/v2/healthz" >&2
    exit 1
  fi
}

check_cors_for_origin "${FRONTEND_URL}"

check_frontend_origin "${FRONTEND_URL}"

for tenant_url in ${TENANT_FRONTEND_URLS}; do
  check_cors_for_origin "${tenant_url}"
  check_frontend_origin "${tenant_url}"
done

echo "Checking built Firebase config in login chunks..."

# A chunk URL can 404 while a frontend rollout is still in flight: the login
# HTML we just fetched may reference chunks from the outgoing build. Retry each
# chunk barely at all so one dead URL cannot eat the whole job budget -- the
# outer loop re-fetches the login HTML instead.
curl_chunk() {
  curl -fsS \
    --retry 1 \
    --retry-delay 1 \
    --retry-all-errors \
    --connect-timeout "${CURL_CONNECT_TIMEOUT_SECONDS}" \
    --max-time "${CURL_MAX_TIME_SECONDS}" \
    "$@"
}

firebase_config_found=0
next_scripts=""
for ((scan_attempt = 1; scan_attempt <= CHUNK_SCAN_ATTEMPTS; scan_attempt++)); do
  login_html="$(curl_smoke "${FRONTEND_URL}/login" || true)"
  next_scripts="$(grep -Eo 'src="[^"]*_next/static/[^"]+\.js"' <<<"${login_html}" |
    sed -E 's/^src="([^"]+)"/\1/' |
    sort -u || true)"

  while IFS= read -r script_path; do
    [[ -n "${script_path}" ]] || continue
    if [[ "${script_path}" == http* ]]; then
      script_url="${script_path}"
    else
      script_url="${FRONTEND_URL%/}${script_path}"
    fi
    if curl_chunk "${script_url}" | grep -qF "${EXPECTED_FIREBASE_PROJECT_ID}"; then
      firebase_config_found=1
      break
    fi
  done <<<"${next_scripts}"

  [[ "${firebase_config_found}" == "1" ]] && break

  if ((scan_attempt < CHUNK_SCAN_ATTEMPTS)); then
    echo "Firebase config not found in login chunks (attempt ${scan_attempt}/${CHUNK_SCAN_ATTEMPTS}); rollout may still be in flight, retrying in ${CHUNK_SCAN_DELAY_SECONDS}s..."
    sleep "${CHUNK_SCAN_DELAY_SECONDS}"
  fi
done

if [[ "${firebase_config_found}" != "1" ]]; then
  if [[ -z "${next_scripts}" ]]; then
    echo "Frontend check failed: could not find Next.js login script chunks at ${FRONTEND_URL}/login" >&2
  else
    echo "Frontend check failed: built Next.js chunks do not contain Firebase project ${EXPECTED_FIREBASE_PROJECT_ID}" >&2
    echo "Chunks scanned:" >&2
    printf '  %s\n' ${next_scripts} >&2
  fi
  exit 1
fi

echo "Checking Stripe webhook signature rejection..."
webhook_status="$(curl_smoke_status -o /dev/null -w '%{http_code}' \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'Stripe-Signature: t=0,v1=invalid' \
  -d '{}' \
  "${API_URL}/api/v2/parent/webhooks/stripe")"
if [[ "${webhook_status}" != "400" ]]; then
  echo "Stripe webhook signature check failed: expected 400 for invalid signature, got ${webhook_status}" >&2
  exit 1
fi

echo "Production smoke checks passed"
