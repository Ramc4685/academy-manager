#!/usr/bin/env bash
set -euo pipefail

BUILD_DIR="${1:-frontend/build}"
EXPECTED_BACKEND_URL="${EXPECTED_BACKEND_URL:-https://api.academy.courtmastr.com}"
EXPECTED_FIREBASE_PROJECT_ID="${EXPECTED_FIREBASE_PROJECT_ID:-academy-courtmastr}"

js_dir="${BUILD_DIR%/}/static/js"
if [[ ! -d "${js_dir}" ]]; then
  echo "Frontend bundle check failed: missing ${js_dir}" >&2
  exit 1
fi

bundle="$(find "${js_dir}" -maxdepth 1 -type f -name '*.js' | head -n 1)"
if [[ -z "${bundle}" ]]; then
  echo "Frontend bundle check failed: no JavaScript bundle found in ${js_dir}" >&2
  exit 1
fi

if ! grep -qF "${EXPECTED_BACKEND_URL}" "${bundle}"; then
  echo "Frontend bundle check failed: built bundle does not contain ${EXPECTED_BACKEND_URL}" >&2
  exit 1
fi

if ! grep -qF "${EXPECTED_FIREBASE_PROJECT_ID}" "${bundle}"; then
  echo "Frontend bundle check failed: built bundle does not contain Firebase project ${EXPECTED_FIREBASE_PROJECT_ID}" >&2
  exit 1
fi

echo "Frontend bundle config verified"
