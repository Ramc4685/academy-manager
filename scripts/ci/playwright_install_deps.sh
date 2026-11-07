#!/usr/bin/env bash
# Install Playwright's apt system dependencies with a per-attempt time limit.
# Run from the frontend directory: scripts/ci/playwright_install_deps.sh chromium
#
# Why: on 2026-11-06 (PR #1155, run 42249006587) azure.archive.ubuntu.com
# served the optional font packages at ~35 kB/s, so `playwright install-deps`
# took ~9.5 minutes and the 12-minute e2e job was cancelled with the tests
# 2 minutes in. Other runners finish the same step in 10-30s. A slow mirror
# should fail fast and retry on the main Ubuntu archive, not eat the job.
set -uo pipefail

browser="${1:?usage: $0 <browser>}"
attempt_seconds="${PLAYWRIGHT_DEPS_ATTEMPT_SECONDS:-150}"

for attempt in 1 2; do
  echo "playwright install-deps ${browser}: attempt ${attempt} (limit ${attempt_seconds}s)"
  if timeout --kill-after=15 "${attempt_seconds}" pnpm exec playwright install-deps "${browser}"; then
    exit 0
  fi
  echo "::warning::playwright install-deps attempt ${attempt} failed or exceeded ${attempt_seconds}s"
  if [ "${attempt}" -eq 1 ]; then
    # timeout cannot reach the root apt-get under sudo (sudo runs it on its own
    # pty), so stop it here or it keeps the dpkg lock. Then finish any dpkg run
    # that was interrupted and switch off the Azure mirror for the retry.
    sudo pkill -x apt-get || true
    sudo pkill -x dpkg || true
    sleep 2
    sudo sed -i 's|azure\.archive\.ubuntu\.com|archive.ubuntu.com|g' \
      /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null || true
    sudo dpkg --configure -a || true
  fi
done

echo "::error::playwright install-deps ${browser} failed after 2 attempts"
exit 1
