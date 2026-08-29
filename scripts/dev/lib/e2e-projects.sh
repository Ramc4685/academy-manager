#!/usr/bin/env bash
# e2e-projects.sh — list the Playwright projects the local gate shards over.
#
# Sourced by pre-push-checks.sh. The names come straight out of
# playwright.config.ts, so adding, renaming, or removing a project stays a
# one-file edit (plus its CI job) and the local gate follows automatically
# instead of silently skipping a browser.
#
# Covered by scripts/dev/pre-push-checks.test.sh.

# Echoes one project name per line, in config order.
e2e_projects() {
  local config="${1:-}"
  if [ -z "$config" ]; then
    config="${FRONTEND:-.}/playwright.config.ts"
  fi
  if [ ! -f "$config" ]; then
    return 1
  fi
  # Only project entries carry a `name:` key in this config; the webServer and
  # use blocks do not.
  sed -n 's/^[[:space:]]*name:[[:space:]]*"\([^"]*\)".*/\1/p' "$config"
}
