#!/usr/bin/env bash
# Per-worktree port derivation for the local e2e stack (#522).
#
# Mirrors frontend/lib/worktree-port.ts — djb2 (h*33 + c) mod 2^32 over the
# repo root path, mapped into ports 3001-3999. The frontend node test
# (frontend/lib/worktree-port.node-test.mjs) cross-checks the two
# implementations, so change both together.
#
# Usage:
#   source scripts/dev/lib/worktree-port.sh
#   port="$(derive_worktree_port "/path/to/repo/root")"
#   port="$(default_frontend_port "/path/to/repo/root")"  # CI-aware default

WORKTREE_PORT_BASE=3001
WORKTREE_PORT_RANGE=999 # ports 3001-3999

derive_worktree_port() {
  local path="$1"
  local h=5381
  local i c
  for ((i = 0; i < ${#path}; i++)); do
    printf -v c '%d' "'${path:i:1}"
    h=$(((h * 33 + c) & 0xFFFFFFFF))
  done
  printf '%d\n' $((WORKTREE_PORT_BASE + (h % WORKTREE_PORT_RANGE)))
}

# CI keeps the historical 3001 (workflows pin LOCAL_AUTH_BASE_URL to
# http://localhost:3001); everywhere else each worktree gets its own port.
default_frontend_port() {
  local repo_root="$1"
  if [ -n "${CI:-}" ]; then
    printf '%d\n' "${WORKTREE_PORT_BASE}"
  else
    derive_worktree_port "${repo_root}"
  fi
}
