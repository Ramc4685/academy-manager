# blno-launch-readiness-fixes

## Current State

Status: active

## Problem

Review-doc P0/P1 fixes: payments error sanitization+ACH polling, coach bulk attendance+dead buttons, admin billing health, timezone rendering, seed uid remap, launch audit validator drift

## Changed Files

- None recorded yet.

## Log

- 2026-07-02T20:55:42 main/NA: Task ledger created.
- 2026-07-02T20:55:42 main/working: All fixes implemented; backend pytest 2052 passed, frontend node tests 58/58, typecheck+lint clean, launch_readiness_audit now pass against staging; docker rebuild with correct Firebase key in progress
- 2026-07-02T21:16:39 main/working: Added coach attendance hydration (attendance_status on /coach/today roster) fixing bulk mark-all 409 + reload state loss; payment-error mapper split portal vs generic + Billing.CheckoutCreationFailed code mapping; backend 2053 passed, frontend 60/60; final docker rebuild in progress
- 2026-07-02T21:23:29 main/working: Diagnosed mark-all 409 as SW stale-while-revalidate + persisted query cache serving stale roster; added 409 recovery (clear local marks + invalidate today query) on bulk attendance; final rebuild running
## Verification

- No verification recorded yet.
- 2026-07-02T21:27:21: Staging UX verified: parent invoices/payment labels/pause-enrollment/sanitized autopay error; coach mark-all-present wrote 135 present rows; admin billing-health healthy-state + expandable notes + dues stage column removed; launch_readiness_audit=pass. Suites: backend pytest 2053 pass, frontend node 60/60, typecheck/lint/ruff clean, coach e2e 9-10 pass (1 pre-existing parallel-load flake)
## Reusable Lessons

- None recorded yet.
