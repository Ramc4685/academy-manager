# security-alert-cleanup-deps

PR: #1088

## What changed
Clears the open Dependabot alerts. Removes `examples/stripe-connect-marketplace/`, a throwaway Stripe Connect sample that carried a critical proxy-addr advisory, several qs/body-parser advisories and three CodeQL reflected-XSS alerts. In the frontend, bumps vitest and @vitest/coverage-v8 to ^4.1.12 (@vitest/mocker advisories) and adds or raises pnpm overrides for `qs` (^6.16.1), `ip-address` (^10.7.1) and `uuid` (^11.1.1; only @lhci/cli uses it, via `v4()`). All affected packages are dev or build tooling. `extract-zip` has no patched release and is reached only through dev tooling, so its alerts are dismissed rather than fixed.

## Deploy notes
No runtime change: dev and build dependencies only. No migrations, no backend change, no new environment variables.

## Risk / rollback
Low. The production bundle's dependencies are unchanged; the risk is limited to test and lighthouse tooling. Roll back by reverting the PR.
