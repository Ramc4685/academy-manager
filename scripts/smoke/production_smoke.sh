#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-https://api.academy.courtmastr.com}"
FRONTEND_URL="${FRONTEND_URL:-https://academy.courtmastr.com}"

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
  "${API_URL}/api/auth/me")"

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

echo "Checking frontend..."
curl -fsSI "${FRONTEND_URL}" >/dev/null

echo "Production smoke checks passed"
