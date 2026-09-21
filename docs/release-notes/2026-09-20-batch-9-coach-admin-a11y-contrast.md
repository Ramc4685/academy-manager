# Batch 9: coach/admin a11y contrast fixes

PR: #851

## What changed
- Fixes #844 — Swapped every contrast-failing colour named in #844 for the design-system token already calibrated for that surface: coach day-group headings, passport skill descriptions, and admin student-progress secondary text now use `text-rally-muted` instead of raw `text-neutral-400`/`text-neutral-500`.
- Fixes #844 — Coach bottom nav's inactive labels use `rally.subtle-ink` (#94a3b8, 7.5:1 on the night nav) instead of `rally.muted` (4.0:1), restoring WCAG AA contrast in the dark nav bar.
- Fixes #844 — "Mark all present" and the selected Present state use `status-green-800` (7.8:1 with white) instead of `green-600` (3.3:1).
- Fixes #844 — The required-skill asterisk uses `status-red-800` for adequate contrast against its background.

## Deploy notes
No migrations. Pure frontend token/class swaps; no schema, API, or config changes. Safe to deploy independently.

## Risk / rollback
Low risk: visual-only changes constrained to color tokens on existing coach and admin surfaces, verified against the full backend and frontend gate (pytest, ruff, lint-imports, mypy-baseline, typecheck, eslint, build). Rollback is a revert of this PR.
