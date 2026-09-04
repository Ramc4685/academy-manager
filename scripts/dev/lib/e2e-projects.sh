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

# Projects CI runs only from the nightly workflow
# (.github/workflows/nightly-e2e.yml), never as a PR check. The local gate
# mirrors that split: these shards are skipped by default and included with
# `--full` or PRE_PUSH_E2E_ALL=1. WebKit under local load misses first-load
# budgets on routes the diff never touched, and failOnFlakyTests then blocks
# pushes that CI itself would accept.
E2E_NIGHTLY_ONLY_PROJECTS="webkit-mobile"

# Echoes the shards the local gate should run: e2e_shard_list minus the
# nightly-only projects, unless $2 is "--full" or PRE_PUSH_E2E_ALL=1. Never
# echoes an empty list; if filtering would leave nothing it fails instead.
e2e_gate_shard_list() {
  local config="${1:-}" full="${2:-}"
  local all
  all="$(e2e_shard_list "$config")" || return 1
  if [ "$full" = "--full" ] || [ "${PRE_PUSH_E2E_ALL:-}" = "1" ]; then
    printf '%s\n' "$all"
    return 0
  fi
  local kept="" project
  while IFS= read -r project; do
    case " $E2E_NIGHTLY_ONLY_PROJECTS " in
      *" $project "*) continue ;;
    esac
    kept="${kept}${kept:+
}$project"
  done <<< "$all"
  if [ -z "$kept" ]; then
    echo "error: every Playwright project is nightly-only — refusing to run zero e2e shards" >&2
    return 1
  fi
  printf '%s\n' "$kept"
}

# Echoes the nightly-only projects present in the config, one per line, for
# the gate's "skipped" notice. Empty when none are configured.
e2e_nightly_only_present() {
  local config="${1:-}"
  local all project
  all="$(e2e_projects "$config")" || return 0
  while IFS= read -r project; do
    case " $E2E_NIGHTLY_ONLY_PROJECTS " in
      *" $project "*) printf '%s\n' "$project" ;;
    esac
  done <<< "$all"
}
