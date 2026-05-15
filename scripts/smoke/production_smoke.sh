#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-https://api.academy.courtmastr.com}"
FRONTEND_URL="${FRONTEND_URL:-https://academy.courtmastr.com}"
EXPECTED_BACKEND_URL="${EXPECTED_BACKEND_URL:-https://api.academy.courtmastr.com}"
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
frontend_headers="$(curl -fsSI "${FRONTEND_URL}")"
if ! grep -qi '^content-type:.*text/html' <<<"${frontend_headers}"; then
  echo "Frontend check failed: expected HTML response from ${FRONTEND_URL}" >&2
  exit 1
fi

frontend_html="$(curl -fsS "${FRONTEND_URL}")"
script_path="$(grep -Eo 'src="[^"]*/static/js/[^"]+\.js"' <<<"${frontend_html}" | head -n 1 | sed -E 's/^src="([^"]+)"/\1/' || true)"
if [[ -z "${script_path}" ]]; then
  echo "Frontend check failed: could not find built JavaScript bundle" >&2
  exit 1
fi

if [[ "${script_path}" == http* ]]; then
  script_url="${script_path}"
else
  script_url="${FRONTEND_URL%/}${script_path}"
fi

bundle="$(curl -fsS "${script_url}")"
if ! grep -qF "${EXPECTED_BACKEND_URL}" <<<"${bundle}"; then
  echo "Frontend check failed: built bundle does not contain ${EXPECTED_BACKEND_URL}" >&2
  exit 1
fi

if ! grep -qF "${EXPECTED_FIREBASE_PROJECT_ID}" <<<"${bundle}"; then
  echo "Frontend check failed: built bundle does not contain Firebase project ${EXPECTED_FIREBASE_PROJECT_ID}" >&2
  exit 1
fi

echo "Production smoke checks passed"
