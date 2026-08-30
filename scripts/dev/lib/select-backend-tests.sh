#!/usr/bin/env bash
# select-backend-tests.sh — focused-test selection for the pre-push hook's
# backend-only tier (#482). Shared by scripts/dev/pre-push-checks.sh and
# scripts/dev/pre-push-checks.test.sh. Pure: no side effects, bash 3.2 safe.
#
# select_backend_tests "<newline-separated backend-relative paths>" [tests_root]
#
# Prints newline-separated, deduplicated pytest targets:
#   - changed test files themselves
#   - <tests_root>/contexts/<name>/ for changed v2/contexts/<name>/ sources
#   - test files that import a changed module (grep for its dotted path)
# Prints nothing when no mapping is found — the caller decides the fallback
# (the hook falls back to the structural suite, which always runs anyway).

select_backend_tests() {
  local changed="${1-}" root="${2:-v2/tests}"
  local f name mod
  {
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      case "$f" in *.py) ;; *) continue ;; esac

      # Changed test files run directly.
      case "$f" in
        v2/tests/*)
          printf '%s\n' "$f"
          continue
          ;;
      esac

      # Context sources map to their mirrored test directory when it exists.
      case "$f" in
        v2/contexts/*/*)
          name="${f#v2/contexts/}"
          name="${name%%/*}"
          if [ -d "$root/contexts/$name" ]; then
            printf '%s\n' "$root/contexts/$name"
          fi
          ;;
      esac

      # Any test file importing the changed module's dotted path.
      mod="${f%.py}"
      mod="${mod%/__init__}"
      mod="${mod//\//.}"
      if [ -d "$root" ]; then
        grep -rl --include='*.py' -F "$mod" "$root" 2>/dev/null || true
      fi
    done <<< "${changed}"
  } | sort -u
}
