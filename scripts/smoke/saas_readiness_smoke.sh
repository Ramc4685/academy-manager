#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8001}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3001}"
TENANT_FRONTEND_URL="${TENANT_FRONTEND_URL:-}"
TENANT_HOST="${TENANT_HOST:-tenant-smoke.localhost}"
INTERNAL_TENANT_HEADER_NAME="${INTERNAL_TENANT_HEADER_NAME:-}"
INTERNAL_TENANT_HEADER_VALUE="${INTERNAL_TENANT_HEADER_VALUE:-}"
UNAPPROVED_INTERNAL_TENANT_HEADER_NAME="${UNAPPROVED_INTERNAL_TENANT_HEADER_NAME:-x-internal-tenant-id}"
AUTH_TOKEN="${AUTH_TOKEN:-}"
STATIC_ONLY=0

for arg in "$@"; do
  case "${arg}" in
    --static-only)
      STATIC_ONLY=1
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      echo "Usage: $0 [--static-only]" >&2
      exit 2
      ;;
  esac
done

if ! command -v rg >/dev/null 2>&1; then
  echo "ripgrep (rg) is required for static SaaS readiness checks" >&2
  exit 1
fi

echo "Checking frontend source for legacy /api/* calls..."
legacy_frontend_matches="$(
  rg -n -P \
    "fetch\\(\\s*['\"]/api/(?!v2(?:/|$))|apiFetch\\(\\s*['\"]/api/(?!v2(?:/|$))|href=\\{?\\s*['\"]/api/(?!v2(?:/|$))" \
    frontend/app frontend/components frontend/lib || true
)"
if [[ -n "${legacy_frontend_matches}" ]]; then
  echo "Frontend SaaS source must not call legacy /api/* paths:" >&2
  echo "${legacy_frontend_matches}" >&2
  exit 1
fi

echo "Checking SaaS request-path code for default_academy_id use..."
default_tenant_matches="$(
  rg -n \
    "settings\\.default_academy_id|getattr\\([^\\n]*default_academy_id|\\.default_academy_id" \
    backend/v2/interfaces backend/v2/shared/auth backend/v2/shared/tenancy || true
)"
if [[ -n "${default_tenant_matches}" ]]; then
  echo "SaaS request paths must not use default_academy_id:" >&2
  echo "${default_tenant_matches}" >&2
  exit 1
fi

if [[ "${STATIC_ONLY}" == "1" ]]; then
  echo "Static SaaS readiness checks passed"
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for HTTP SaaS readiness checks" >&2
  exit 1
fi

status_code() {
  curl -sS -o /tmp/saas-readiness-body.$$ -w '%{http_code}' "$@"
}

echo "Checking v2 health endpoint..."
v2_health_body="$(curl -fsS "${API_URL}/api/v2/healthz")"
if ! grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' <<<"${v2_health_body}"; then
  echo "v2 health check failed for ${API_URL}/api/v2/healthz" >&2
  exit 1
fi

echo "Checking legacy route is gone in SaaS mode..."
legacy_code="$(status_code "${API_URL}/api/health")"
if [[ "${legacy_code}" != "410" ]]; then
  echo "Expected ${API_URL}/api/health to return 410 in SaaS mode, got ${legacy_code}" >&2
  echo "Start the backend with V2_ENABLED=1 and V2_SAAS_MODE=true for this smoke." >&2
  exit 1
fi

echo "Checking unknown tenant host does not get anonymous tenant access..."
unknown_code="$(status_code -H "Host: ${TENANT_HOST}" "${API_URL}/api/v2/me")"
if [[ "${unknown_code}" != "401" && "${unknown_code}" != "403" ]]; then
  echo "Expected unknown/unauthenticated tenant /api/v2/me to return 401 or 403, got ${unknown_code}" >&2
  exit 1
fi

if [[ -n "${AUTH_TOKEN}" ]]; then
  echo "Checking unknown tenant host rejects authenticated requests too..."
  unknown_auth_code="$(
    status_code \
      -H "Host: ${TENANT_HOST}" \
      -H "Authorization: Bearer ${AUTH_TOKEN}" \
      "${API_URL}/api/v2/me"
  )"
  if [[ "${unknown_auth_code}" != "401" && "${unknown_auth_code}" != "403" ]]; then
    echo "Expected authenticated unknown-tenant /api/v2/me to return 401 or 403, got ${unknown_auth_code}" >&2
    exit 1
  fi

  echo "Checking authenticated /api/v2/me still requires explicit tenant resolution..."
  no_tenant_code="$(
    status_code \
      -H "Authorization: Bearer ${AUTH_TOKEN}" \
      "${API_URL}/api/v2/me"
  )"
  if [[ "${no_tenant_code}" == "200" ]]; then
    echo "Expected authenticated /api/v2/me without tenant host/header to be rejected, got 200" >&2
    exit 1
  fi
fi

if [[ -n "${INTERNAL_TENANT_HEADER_NAME}" && -n "${INTERNAL_TENANT_HEADER_VALUE}" ]]; then
  echo "Checking approved internal tenant header path..."
  header_args=(-H "${INTERNAL_TENANT_HEADER_NAME}: ${INTERNAL_TENANT_HEADER_VALUE}")
  if [[ -n "${AUTH_TOKEN}" ]]; then
    header_args+=(-H "Authorization: Bearer ${AUTH_TOKEN}")
  fi
  internal_code="$(status_code "${header_args[@]}" "${API_URL}/api/v2/me")"
  if [[ -n "${AUTH_TOKEN}" ]]; then
    if [[ "${internal_code}" != "200" ]]; then
      echo "Expected internal-header authenticated /api/v2/me to return 200, got ${internal_code}" >&2
      exit 1
    fi
  elif [[ "${internal_code}" != "401" && "${internal_code}" != "403" ]]; then
    echo "Expected internal-header unauthenticated /api/v2/me to return 401 or 403, got ${internal_code}" >&2
    exit 1
  fi
else
  echo "Skipping internal tenant header check; set INTERNAL_TENANT_HEADER_NAME and INTERNAL_TENANT_HEADER_VALUE to enable it."
  if [[ -n "${AUTH_TOKEN}" ]]; then
    echo "Checking internal tenant header is not accepted when smoke config omits it..."
    unapproved_code="$(
      status_code \
        -H "${UNAPPROVED_INTERNAL_TENANT_HEADER_NAME}: smoke-unapproved" \
        -H "Authorization: Bearer ${AUTH_TOKEN}" \
        "${API_URL}/api/v2/me"
    )"
    if [[ "${unapproved_code}" == "200" ]]; then
      echo "Internal tenant header returned 200 even though this smoke did not configure an approved header." >&2
      exit 1
    fi
  fi
fi

echo "Checking frontend v2 proxy if frontend is reachable..."
frontend_code="$(status_code "${FRONTEND_URL}/api/v2/healthz" || true)"
if [[ "${frontend_code}" == "200" ]]; then
  if ! grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' /tmp/saas-readiness-body.$$; then
    echo "Frontend v2 proxy returned 200 but did not include v2 health body" >&2
    exit 1
  fi
else
  echo "Frontend proxy check skipped or unavailable at ${FRONTEND_URL} (status ${frontend_code})."
fi

if [[ -n "${AUTH_TOKEN}" ]]; then
  echo "Checking frontend proxy does not infer tenant from auth alone..."
  frontend_no_tenant_code="$(
    status_code \
      -H "Authorization: Bearer ${AUTH_TOKEN}" \
      "${FRONTEND_URL}/api/v2/me" || true
  )"
  if [[ "${frontend_no_tenant_code}" == "200" ]]; then
    echo "Expected frontend proxy /api/v2/me without tenant host to be rejected, got 200" >&2
    exit 1
  fi
fi

if [[ -n "${TENANT_FRONTEND_URL}" && -n "${AUTH_TOKEN}" ]]; then
  echo "Checking tenant frontend login page and authenticated v2 proxy..."
  login_code="$(status_code "${TENANT_FRONTEND_URL}/login" || true)"
  if [[ "${login_code}" == "200" || "${login_code}" == "307" || "${login_code}" == "308" ]]; then
    echo "Checking tenant frontend proxy preserves Authorization and tenant host for /api/v2/me..."
    tenant_proxy_code="$(
      status_code \
        -H "Authorization: Bearer ${AUTH_TOKEN}" \
        "${TENANT_FRONTEND_URL}/api/v2/me" || true
    )"
    if [[ "${tenant_proxy_code}" != "200" ]]; then
      echo "Expected tenant frontend proxy /api/v2/me to preserve Authorization and tenant host, got ${tenant_proxy_code}" >&2
      exit 1
    fi
  else
    echo "Tenant frontend login/proxy check skipped or unavailable at ${TENANT_FRONTEND_URL} (status ${login_code})."
  fi
else
  echo "Skipping tenant frontend authenticated proxy check; set TENANT_FRONTEND_URL and AUTH_TOKEN to enable it."
fi

echo "SaaS readiness smoke checks passed"
