#!/usr/bin/env bash
set -euo pipefail

if [ "${CLAUDE_CODE_STOP_HOOK_ACTIVE:-}" = "true" ]; then
  exit 0
fi

project_dir="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "${project_dir}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

changed_files="$(git status --short --untracked-files=no | sed -n '1,40p')"
if [ -z "${changed_files}" ]; then
  exit 0
fi

cat <<'EOF'
Verification reminder: this repo expects final answers to state the exact checks run, results, skipped checks, and why. Update the active docs/test-results/active ledger when code or verification state changed.
EOF
