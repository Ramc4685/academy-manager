# production legacy conversion review

## Current State

Status: active

## Problem

Review and design a safe read-only plan to convert remaining production legacy data/compatibility paths before making any production changes.

## Changed Files

- None recorded yet.

## Log

- 2026-06-19T23:18:03 main/NA: Task ledger created.
- 2026-06-19T23:18:42 main/working: Read-only context pass complete. Existing runbook supports legacy payments retirement via backfill, archive, launch audit, and UI smoke. Current docs also show non-billing compatibility surfaces remain: identity legacy fields, student dob/parent_user_id, waivers, session normalization, coach-rate seed fields, messages/comms. No production changes run.
- 2026-06-19T23:23:58 main/working: Approach B approved. Wrote review spec docs/superpowers/specs/2026-06-20-production-billing-legacy-conversion-design.md. No production commands or app code changes run.
- 2026-06-19T23:39:01 main/working: Spec approved. Created implementation plan docs/superpowers/plans/2026-06-20-production-billing-legacy-conversion.md. No production commands or code implementation run.
- 2026-06-19T23:43:27 main/working: Task 1 complete: added failing backfill mapping tests for invoice_number preservation, discounted pending balances, partial payments, partial alias, and parent balance reconciliation. Focused test run is red as expected: 5 failed, 22 passed.
- 2026-06-20T00:07:46 main/working: Task 2 complete: hardened legacy payment mapper for invoice_number preservation, strict cents parsing, net/final amounts, partial and overpayment handling, status-first reconciliation, dynamic status reporting, academy-scoped/per-collection idempotent writes. Reviews passed. Focused reviewer run covered 55 tests plus ruff format/check.
- 2026-06-20T00:12:01 main/working: Task 3 complete: extracted/verified injectable backfill_legacy_payments helper, run_backfill now delegates and closes client in finally, added cross-academy idempotency contract coverage. Reviews passed; focused verification 44 tests plus ruff format/check.
- 2026-06-20T00:19:41 main/working: Task 4 complete: added archive contract coverage for invoice-number-preserving backfills and launch-readiness pass coverage after legacy payment archive. Reviews passed; focused verification 14 tests plus ruff format/check.
- 2026-06-20T00:20:22 main/working: Added BLNO billing legacy conversion operator runbook; no production commands run.
- 2026-06-20T00:26:59 main/working: Task 5 complete: added BLNO production billing legacy conversion runbook with explicit gates, inline guarded MONGO_URL command examples, launch-audit checks, smoke checklist, and rollback notes. Reviews passed; no production commands run.
## Verification

- No verification recorded yet.
- 2026-06-19T23:23:58: Spec self-review: scanned for TBD/TODO/placeholders; checked scope remains billing-only; confirmed production gates require dry-run review and explicit approval before any write. No tests run because this step only created a design doc.
- 2026-06-19T23:39:01: Plan self-review: checked coverage against approved billing-only spec, removed placeholder/filler commands, kept production dry-run/apply/archive as separate approval gates. No tests run because this step created a plan doc only.
- 2026-06-20T00:27:32: Focused backfill/archive/audit tests passed; ruff format/check passed for touched Python files. No production commands run.
- 2026-06-20T00:32:09: Production BLNO backfill dry-run executed read-only through Fly app env using reviewed local script piped over SSH. Result: 126 legacy payments found; statuses pending=58, succeeded=62, waived=6; deleted skips=0; unknown-status skips=0; already-backfilled skips=0; would write invoices=126, invoice_lines=126, ledger_payments=65, payment_allocations=65; balance reconciliation mismatches=0; no ERROR/WARNING/Traceback lines in /tmp/blno-backfill-dry-run-20260620.log. No production writes run.
- 2026-06-20T00:32:39: Post-dry-run local verification after stdin execution compatibility patch: pytest backend/v2/tests/unit/test_backfill_p4_mapping.py backend/v2/tests/contract/test_backfill_p4_legacy_payments.py -q passed (44 passed); ruff format --check and ruff check passed for backfill script plus focused tests.
- 2026-06-20T00:32:52: Final focused verification before review handoff: pytest backend/v2/tests/unit/test_backfill_p4_mapping.py backend/v2/tests/contract/test_backfill_p4_legacy_payments.py backend/v2/tests/contract/test_archive_legacy_payments.py backend/v2/tests/contract/test_launch_readiness_audit.py -q passed (58 passed).
- 2026-06-20T00:33:29: Read-only production spot check for dry-run count delta: 3 non-succeeded legacy rows have received money and explain ledger_payments=65 vs succeeded=62. Rows: BLNO-202605-721695 pending total=7000 paid=6000 balance=1000; BLNO-202604-8c8b5f pending total=6000 paid=3500 balance=2500; BLNO-202604-1ca7ce pending total=7000 paid=6000 balance=1000. No production writes run.
- 2026-06-20T00:37:35: Production backfill apply completed after scoped backup /tmp/blno-prod-billing-backup-20260620-003523.json.gz. Apply result: 126 legacy rows processed; statuses pending=58, succeeded=62, waived=6; balance mismatches=0; no errors/warnings. Post-apply dry-run idempotency: would write invoices=0, invoice_lines=0, ledger_payments=0, payment_allocations=0; mismatches=0. Direct read-only verification: legacy_active_rows=126, paid_rows_expected=65, generated_invoices=126, generated_invoice_lines=126, generated_ledger_payments=65, generated_allocations=65, all missing counts=0. Original failing payment pay_28505f6db2b4a5b11917 now has invoice inv-from-pay_28505f6db2b4a5b11917 / BLNO-202605-b11917, status=open, balance_due_cents=6000. Legacy archive not applied.
- 2026-06-20T00:45:18: Production legacy payment archive apply completed after explicit approval. Archive result: archiveable=126, archived=126, deleted_from_payments=126, blockers=[]; post-cleanup direct read-only verification: active_payments=0, active_legacy_payments=0, archived_legacy_payments=126, generated_invoices=126, generated_invoice_lines=126, generated_ledger_payments=65, generated_allocations=65. Post-cleanup archive dry-run: archiveable=0, legacy_shaped=0, ledger_shaped=0, blockers=[].
## Reusable Lessons

- None recorded yet.
