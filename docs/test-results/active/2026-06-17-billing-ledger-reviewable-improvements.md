# billing ledger reviewable improvements

## Current State

Status: active

## Problem

Implement small, reviewable billing ledger improvements for tuition invoices, pending and post-generation misc charges, invoice adjustments, autopay notice timing, scheduled monthly generation, parent billing visibility, and admin manual payment handling.

## Changed Files

- None recorded yet.

## Log

- 2026-06-17T19:09:49 main/NA: Task ledger created.
- 2026-06-17T19:09:53 main/working: Kickoff inspection started: read AGENTS-provided rules, README.md, DEPLOYMENT.md, test_result.md, relevant billing ledgers, docs/agent rules, ticket sheets, and started evidence gathering before any code edits.
- 2026-06-18T06:11:36 main/working: User approved running pending v2 migrations against the SaaS staging database, then re-inspecting schema/collections.
- 2026-06-18T06:26:46 main/working: Starting legacy payments cleanup: inspect existing backfill, reads/writes, and indexes before code edits.
- 2026-06-18T06:50:58 main/working: Moved admin billing UI read models off legacy payments: admin payments/dues/reports, student dues status, payment-risk audience, and invoice-row action guard now use ledger invoices/payments.
- 2026-06-18T07:05:04 side/working: Added invoice-native admin actions for manual payment, adjustment, and refund: backend invoice adjustment/refund endpoints, ledger payment refund persistence, frontend invoice dialog actions/API wrappers.
- 2026-06-18T07:15:59 main/working: Added launch index/validator migration, real Mongo launch audit coverage for validators/billing/dead letters/webhooks, and dispatcher typed-event rehydration for dead-letter convergence.
- 2026-06-18T07:55:33 main/working: Completed P1/P2 implementation: added broader domain validators, durable outbox status/retry/lock migration, atomic dispatcher claiming, retry scheduling, replay compatibility, and launch audit outbox health.
## Verification

- No verification recorded yet.
- 2026-06-18T06:12:37: Ran v2 migration runner against local SaaS staging DB mongodb://127.0.0.1:27017/academy_manager_saas_staging; runner reported just_applied_count=0 because 40 migrations were already recorded. Post-run inspection found ledger collections and indexes present; validators remain absent.
- 2026-06-18T06:33:55: Legacy payments cleanup implemented and verified. Local SaaS staging: applied migration 0131, backfilled 116 BLNO legacy payments to ledger records with zero balance mismatches, archived/deleted 116 payments rows into legacy_payments_archive, and launch_readiness_audit passed for PRIMARY_ACADEMY_ID=blno.
- 2026-06-18T06:34:38: Focused verification: pytest v2/tests/unit/test_backfill_p4_mapping.py v2/tests/contract/test_migrations_legacy_compat.py v2/tests/contract/test_archive_legacy_payments.py v2/tests/contract/test_launch_readiness_audit.py v2/tests/contract/test_billing_ledger_storage.py -q passed (44 tests); ruff check passed for touched scripts/migration/tests; git diff --check passed; local launch_readiness_audit passed for blno after archive.
- 2026-06-18T06:50:58: Backend affected suites: cd backend && source .venv/bin/activate && pytest v2/tests/unit/test_admin_composition_tenancy.py v2/tests/application/test_admin_reports_dashboard.py v2/tests/contract/test_admin_directory_mongo_student_repo.py v2/tests/infrastructure/test_mongo_audience_resolver.py v2/tests/contract/test_archive_legacy_payments.py v2/tests/contract/test_launch_readiness_audit.py v2/tests/unit/test_backfill_p4_mapping.py v2/tests/contract/test_migrations_legacy_compat.py v2/tests/contract/test_billing_ledger_storage.py -q => 79 passed.
- 2026-06-18T06:50:58: Frontend focused checks: cd frontend && node --no-warnings --test lib/admin-billing-reconciliation-ui.node-test.mjs => 2 passed; cd frontend && pnpm typecheck => passed.
- 2026-06-18T06:50:58: Launch audit on local cleaned staging: APP_TENANCY_MODE=single_academy ENABLE_PLATFORM_ROUTES=false ENABLE_OWNER_ROLE=false ENABLE_STUDENT_LOGIN=false PRIMARY_ACADEMY_ID=blno python scripts/launch_readiness_audit.py --mongo-url mongodb://127.0.0.1:27017 --db-name academy_manager_saas_staging --primary-academy-id blno => status pass; database pass; legacy_payment_retirement pass; parent_membership_review manual_review.
- 2026-06-18T07:05:04: Invoice-native focused backend tests: cd backend && source .venv/bin/activate && pytest v2/tests/interface/test_admin_billing.py::test_add_invoice_adjustment_allows_negative_discount_line v2/tests/interface/test_admin_billing.py::test_record_invoice_manual_payment_route v2/tests/interface/test_admin_billing.py::test_refund_invoice_route_uses_invoice_native_use_case v2/tests/contract/test_mongo_payment_repo.py::test_get_and_save_ledger_payment_without_recreating_legacy_payment -q => 4 passed.
- 2026-06-18T07:05:04: Broader affected backend suites: cd backend && source .venv/bin/activate && pytest v2/tests/interface/test_admin_billing.py v2/tests/contract/test_mongo_payment_repo.py v2/tests/contract/test_billing_ledger_storage.py v2/tests/unit/test_admin_composition_tenancy.py -q => 74 passed.
- 2026-06-18T07:05:04: Frontend invoice-native checks: cd frontend && node --no-warnings --test lib/admin-billing-reconciliation-ui.node-test.mjs => 3 passed; cd frontend && pnpm typecheck => passed; frontend lint passed inside pre-push.
- 2026-06-18T07:05:04: Full pre-push --full was attempted and failed before completion: ruff format --check v2 reported formatting needed in untracked/other migration 0132_launch_indexes_and_validators.py and several existing touched files; pytest v2/tests had 10 failures caused by 0132 Mongo validators calling mongomock db.command; E2E was interrupted after 80 passed, 8 skipped, 2 interrupted, 110 not run.
- 2026-06-18T07:05:43: Post-format focused checks: cd backend && source .venv/bin/activate && ruff check v2/interfaces/admin/billing_routes.py v2/interfaces/admin/deps.py v2/composition/admin.py v2/contexts/billing/infrastructure/mongo_payment_repo.py v2/tests/interface/test_admin_billing.py v2/tests/contract/test_mongo_payment_repo.py => passed; focused invoice-native tests => 4 passed; git diff --check => passed. Full pre-push remains blocked by unrelated untracked 0132 validator migration.
- 2026-06-18T07:15:59: Real local Mongo smoke: migration 0132 applied to academy_manager_saas_staging; launch_readiness_audit now passes with validators/indexes observed, billing consistency pass, legacy payment retirement pass, webhook health pass, unrecovered dead letters 0.
- 2026-06-18T07:25:26: Full verification passed: backend pytest v2/tests -q (1396 passed), frontend node unit tests (33 passed), pnpm typecheck, pnpm lint, pnpm build, and scripts/dev/pre-push-checks.sh --full including Playwright E2E after sandbox escalation.
- 2026-06-18T07:55:33: Real local Mongo smoke: migration 0133 applied to academy_manager_saas_staging; expanded launch_readiness_audit passes with all P0/P1/P2 validators observed, outbox worker indexes present, billing consistency pass, outbox health pass, and unrecovered dead letters 0.
- 2026-06-18T07:59:23: Full verification after P1/P2 passed: backend pytest v2/tests -q (1403 passed), frontend node unit tests (33 passed), pnpm typecheck, pnpm lint, pnpm build, and scripts/dev/pre-push-checks.sh --full including Playwright E2E.
- 2026-06-18T08:08:03: Review fixes applied: waitlist validator allows skipped, validator audit compares exact expected schemas, outbox health fails due pending/retry/stale/terminal work, replay marks dead letters resolved and rewrites nested event_id, payment-risk audience resolves SaaS global users through memberships. Real local Mongo launch audit passes after reapplying 0133.
- 2026-06-18T08:27:00: Full pre-push verification after P1/P2 validators, outbox retry-lock, UI lint/E2E stability fixes: scripts/dev/pre-push-checks.sh --full passed (backend ruff format/check, pytest v2/tests, frontend node unit tests, typecheck, lint, and pnpm e2e).
- 2026-06-18T08:47:13: BLNO seed cleanup verified: normal local_test_stack seed path and scripts/dev/seed_blno_staging.py both smoke-tested against disposable real Mongo DBs, replayed all v2 migrations after seed, and launch_readiness_audit passed with validators/indexes present, active_legacy_payment_rows=0, users_with_stripe_customer_id=0, and parent membership provenance clean. Focused migration/attendance/seed/audit tests passed (26 passed); full backend pytest v2/tests -q passed (1404 passed, 5 warnings); ruff check passed for changed migration runner files.
- 2026-06-18T08:50:23: SaaS staging orchestrator updated for launch schema changes: scripts/dev/saas_staging.sh now replays v2 migrations after seed/smoke, runs launch audit after blno-seed, exposes an audit command, and reads nested BLNO credential files. Verified bash -n scripts/dev/saas_staging.sh and simple seed+run_all_migrations+launch_readiness_audit on disposable real Mongo DB passed with active_legacy_payment_rows=0 and users_with_stripe_customer_id=0.
## Reusable Lessons

- None recorded yet.
