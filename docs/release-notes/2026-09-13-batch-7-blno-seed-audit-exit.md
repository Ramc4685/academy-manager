# Batch 7: blno-seed audit exit-code fix

## What changed
- Fixes #594 — `blno-seed` ran `launch_audit blno` unconditionally under `set -euo pipefail`, so any launch-readiness finding anywhere in the stack (not just seed-related issues) turned into the seed script's own non-zero exit code, making an otherwise-successful seed look like a failure. The seed now runs the audit for visibility only, prints its JSON output, warns on findings, and exits 0 for audit findings; a genuinely failing seed step (Docker/Mongo/venv errors, etc.) still fails the script.
- Exposed the strict, exit-on-findings run as `saas_staging.sh launch-audit blno` (aliased to the existing `audit` subcommand) for callers (e.g. CI) that do want a non-zero exit on launch-readiness findings.
- Fixed `usage()` in `saas_staging.sh` so newly documented subcommands don't fall off its fixed `sed 3,35p` window.
- Added `scripts/dev/saas_staging_test.sh`: hermetic bash tests (no Docker/Mongo/venv) covering the new exit-code behavior and the `launch-audit`/`audit` alias.
- Added `backend/v2/tests/contract/test_blno_seed_billing_consistency.py`, a contract test proving the seed's own ledger rows satisfy `audit_billing_consistency`.
- Verified (read-only) against a real, previously-seeded staging Mongo instance (1622 invoices, 821 ledger payments): zero billing-consistency failures, confirming the seed script itself is not a source of the billing-audit findings that were previously masking as seed failures. Traced the seed's ledger writes to a single call site (`_upsert_ledger_from_seed_payment` → `map_legacy_payment`).
- Docker was unavailable in this environment, so a from-scratch stack seed+audit run (as opposed to the contract test and the read-only staging check) was not exercised here.

## Deploy notes
- No migrations. No database or infrastructure changes.
- Dev-tooling only (`scripts/dev/saas_staging.sh`, new `scripts/dev/saas_staging_test.sh`); no production runtime code paths are touched.

## Risk / rollback
- Low risk: the change narrows the seed script's exit-code semantics (audit findings no longer fail the seed) and is covered by new hermetic bash tests plus a backend contract test. The strict audit path remains available via `saas_staging.sh launch-audit blno` / `audit` for anyone who wants the old fail-on-findings behavior.
- Rollback: revert this PR. No data or migration cleanup required.

PR: #0
