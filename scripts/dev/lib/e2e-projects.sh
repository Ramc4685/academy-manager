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

# Echoes the shard list, or fails with a message on stderr. A missing config
# or an empty project list is an ERROR here, never an empty loop: `for p in
# $(e2e_projects)` used to swallow the exit code and run zero e2e shards
# while the gate still exited 0.
e2e_shard_list() {
  local projects
  if ! projects="$(e2e_projects "${1:-}")"; then
    echo "error: cannot read Playwright config for the e2e shard list" >&2
    return 1
  fi
  if [ -z "$projects" ]; then
    echo "error: Playwright config lists no projects — refusing to run zero e2e shards" >&2
    return 1
  fi
  printf '%s\n' "$projects"
}
