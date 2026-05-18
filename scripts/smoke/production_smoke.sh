#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-https://api.academy.courtmastr.com}"
FRONTEND_URL="${FRONTEND_URL:-https://academy.courtmastr.com}"
EXPECTED_FIREBASE_PROJECT_ID="${EXPECTED_FIREBASE_PROJECT_ID:-academy-courtmastr}"

echo "Checking API health..."
health_body="$(curl -fsS "${API_URL}/api/health")"
if ! grep -q '"ok"[[:space:]]*:[[:space:]]*true' <<<"${health_body}"; then
  echo "API health check failed: expected \"ok\":true from ${API_URL}/api/health" >&2
  exit 1
fi

echo "Checking API CORS preflight..."
cors_headers="$(curl -fsS -D - -o /dev/null -X OPTIONS \
  -H "Origin: ${FRONTEND_URL}" \
  -H "Access-Control-Request-Method: GET" \
  "${API_URL}/api/v2/me")"

allow_origin="$(awk 'tolower($0) ~ /^access-control-allow-origin:/ {
  sub(/^[^:]*:[[:space:]]*/, "")
  sub(/\r$/, "")
  print
  exit
}' <<<"${cors_headers}")"

allow_origin_lower="$(printf '%s' "${allow_origin}" | tr '[:upper:]' '[:lower:]')"
frontend_url_lower="$(printf '%s' "${FRONTEND_URL}" | tr '[:upper:]' '[:lower:]')"

if [[ "${allow_origin_lower}" != "${frontend_url_lower}" ]]; then
  echo "CORS preflight failed: expected access-control-allow-origin ${FRONTEND_URL}, got ${allow_origin:-<missing>}" >&2
  exit 1
fi

echo "Checking v2 API health..."
v2_health_body="$(curl -fsS "${API_URL}/api/v2/healthz")"
if ! grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' <<<"${v2_health_body}"; then
  echo "v2 API health check failed: expected \"status\":\"ok\" from ${API_URL}/api/v2/healthz" >&2
  exit 1
fi

echo "Checking frontend..."
frontend_headers="$(curl -fsSI "${FRONTEND_URL}")"
if ! grep -qi '^content-type:.*text/html' <<<"${frontend_headers}"; then
  echo "Frontend check failed: expected HTML response from ${FRONTEND_URL}" >&2
  exit 1
fi

frontend_html="$(curl -fsS "${FRONTEND_URL}")"
if ! grep -qiE 'CourtMastr|Academy Manager|badminton|Run your' <<<"${frontend_html}"; then
  echo "Frontend check failed: expected CourtMastr/Academy content from ${FRONTEND_URL}" >&2
  exit 1
fi

echo "Checking frontend BFF proxy..."
frontend_v2_health_body="$(curl -fsS "${FRONTEND_URL}/api/v2/healthz")"
if ! grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' <<<"${frontend_v2_health_body}"; then
  echo "Frontend BFF proxy check failed: expected \"status\":\"ok\" from ${FRONTEND_URL}/api/v2/healthz" >&2
  exit 1
fi

mapfile -t next_scripts < <(
  grep -Eo 'src="[^"]*_next/static/[^"]+\.js"' <<<"${frontend_html}" |
    sed -E 's/^src="([^"]+)"/\1/' |
    sort -u
)
if [[ "${#next_scripts[@]}" -eq 0 ]]; then
  echo "Frontend check failed: could not find Next.js script chunks" >&2
  exit 1
fi

firebase_config_found=0
for script_path in "${next_scripts[@]}"; do
  if [[ "${script_path}" == http* ]]; then
    script_url="${script_path}"
  else
    script_url="${FRONTEND_URL%/}${script_path}"
  fi
  if curl -fsS "${script_url}" | grep -qF "${EXPECTED_FIREBASE_PROJECT_ID}"; then
    firebase_config_found=1
    break
  fi
done

if [[ "${firebase_config_found}" != "1" ]]; then
  echo "Frontend check failed: built Next.js chunks do not contain Firebase project ${EXPECTED_FIREBASE_PROJECT_ID}" >&2
  exit 1
fi

echo "Checking Stripe webhook signature rejection..."
webhook_status="$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'Stripe-Signature: t=0,v1=invalid' \
  -d '{}' \
  "${API_URL}/api/webhook/stripe")"
if [[ "${webhook_status}" != "400" ]]; then
  echo "Stripe webhook signature check failed: expected 400 for invalid signature, got ${webhook_status}" >&2
  exit 1
fi

echo "Production smoke checks passed"
