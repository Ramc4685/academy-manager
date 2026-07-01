# autopay requirements completion audit

## Current State

Status: active

## Problem

Map 2026-06-30 autopay ACH card-fee review requirements to current Slice H worktree commits and identify remaining implementation gaps before the next slice.

## Requirement Audit Matrix

Source: `/Users/ramc/Documents/Code/academy-manager/docs/requirements/2026-06-30-autopay-ach-card-fee-requirements-review-v2.md` (shared checkout; not present in this worktree).

| # | Requirement | Current evidence | Status |
|---|---|---|---|
| 1 | App-owned off-session recurring-charge mechanism | `enroll_child_in_session_type.py` starts setup checkout so the app owns future invoices and persists `stripe_subscription_id=None`; `ChargeInvoiceViaAutopay` owns off-session PI creation. | Code evidence supports complete. |
| 2 | Default payment method write gap | `CompleteAutopaySetup` calls `set_customer_default_payment_method`; Stripe adapter writes `invoice_settings.default_payment_method`; parent projection is promoted only for active primary PMs. | Code evidence supports complete. |
| 3 | Setup-completion tenant re-home, no subscription rows on setup path | Setup completion validates `academy_id`, parent, enrollment, SetupIntent, customer, and payment method from metadata/Stripe before persisting. | Code evidence supports complete. |
| 4 | Delete 2 leftover historical `subscriptions` rows | Added `scripts/dev/cleanup_stale_tuition_subscriptions.py`, a dry-run-first utility that selects only incomplete setup-bookkeeping rows with no Stripe subscription id and requires explicit confirmation for deletion. No production data operation was run in this audit. | Cleanup path implemented; production deletion remains external/unverified. |
| 5 | Split enrollment status from last attempt outcome, include `paused` | `domain/autopay_status.py` defines `autopay_enrollment_status` and `AutopayAttemptOutcome`; `MongoStudentBillingEnrollmentRepository` has guarded enrollment transitions and records attempt outcome independently. | Code evidence supports complete. |
| 6 | Cycle/amount-scoped idempotency, dunning retry scope | PI keys are `autopay:{invoice}:{period}:{balance}` with optional `retry_scope`; attempt keys include invoice/period/amount/retry scope/status/PI. | Code evidence supports complete. |
| 7 | Fee model aligned to cash-discount policy/funding type | `BillingSettings` stores academy-scoped ACH discount policy; `compute_ach_discount` applies only to ACH funding and fail-safes to no discount for card/debit/prepaid/unknown; card surcharge/processing fee is intentionally absent. | Code evidence supports complete for chosen cash-discount path. |
| 8 | Append-only consent log, ACH mandate distinct from card disclosure | `AutopayConsent` model and `MongoAutopayConsentRepository` write `autopay_consents`; setup completion records `consent_text_version`, `ach_mandate_version`, and `card_disclosure_version` separately. | Code evidence supports complete. |
| 9 | ACH lifecycle: processing/pending, microdeposit, return/reversal | Charge use case records `processing` without allocation; webhook handler records processing attempts, supports verification-required ACH setup, and maps Nacha return codes for ACH return/clawback handling. | Code evidence supports complete. |
| 10 | Dunning/retry ladder | `domain/dunning.py`, `ProcessDunningRetries`, Mongo dunning repo, scheduler/admin wiring implement retry schedule, leases, parking, terminal dunning, notifications, and terminal autopay disable retry. | Code evidence supports complete. |
| 11 | Card fallback schema decision/model | Setup metadata supports `payment_method_role` primary/fallback; parent billing customer repo stores `autopay_payment_methods` plus primary/fallback projections; fallback card does not activate/default enrollment. | Code evidence supports complete. |
| 12 | Invoice numbering prefix, atomic counter, gap policy | `LedgerInvoice.invoice_number` documents gap policy; `format_invoice_number`, `BillingSettings.invoice_number_prefix`, and `MongoBillingCounterRepository.next_value` provide per-academy/month atomic counters; contract tests cover concurrency/isolation/prefix. | Code evidence supports complete. |
| 13 | `autopay_eligible` denormalization decision | `rg autopay_eligible backend/v2 frontend docs` returned no matches. Charge eligibility is derived at charge time from per-enrollment `autopay_enrollment_status`. | Code evidence supports complete. |
| 14 | Single account vs Connect tenant assumption | Current implementation chose Connect-per-academy: `ConnectedAccount` domain, setup `on_behalf_of`, destination charges via `transfer_data.destination`, and Connect webhook tenant guard. | Code evidence supports complete. |
| 15 | Fee-in-refunds and Stripe-fee-vs-parent-fee reconciliation | For the chosen ACH cash-discount path, full invoice refunds write ACH discount reversal credit-note audit rows; partial refunds leave discount unreversed. No parent card surcharge exists to reconcile against Stripe fees. | Code evidence supports complete for chosen cash-discount path. |
| 16 | ACH-aware reconciliation treats processing as non-erroring | Reconciler skips non-`succeeded` PaymentIntents; ACH `processing` is recorded as a payment attempt without ledger allocation. | Code evidence supports complete. |
| 17 | Reuse billing-health UI for admin visibility | Existing `/admin/billing-health` page now fetches dunning failures and renders the `Dunning Ladder` table; billing-health Playwright spec covers the page. | Code evidence supports complete. |

## Current Audit Conclusion

Implementation requirements visible from code are covered by current Slice H worktree commits through `f84874a8`, with an additional safe cleanup utility added afterward for the historical subscriptions-row cleanup item. The actual production deletion of the two leftover `subscriptions` rows is still not proved by local code and was not run in this audit, so this ledger does not claim the entire broader goal is complete.

The review document's §11 says the concrete edits are "to be made by the author, not here." This audit treats those edits as requirement-authoring guidance, while verifying the code outcomes requested by the checklist and subsequent slices.

## Changed Files

- `test_result.md` — active ledger index updated by `scripts/dev/test_result.py start`.
- `docs/test-results/active/2026-07-01-autopay-requirements-completion-audit.md` — checkpoint ledger for the requirement completion audit.
- `scripts/dev/cleanup_stale_tuition_subscriptions.py` — dry-run-first audit/delete utility for stale tuition subscription setup rows.
- `backend/v2/tests/unit/test_cleanup_stale_tuition_subscriptions.py` — unit coverage for candidate selection, defensive delete filter, and explicit apply confirmation.

## Log

- 2026-07-01T14:59:18 main/NA: Task ledger created.
- 2026-07-01T14:59:29 main/working: Checkpoint after Slice K: current worktree main/slice-h is at beca87c5. Requirement audit found current code evidence for status split, scoped idempotency, cash-discount fee policy, append-only consent, ACH pending/returns, dunning retry ladder, fallback method projection, invoice numbering, Connect routing, and billing-health dunning UI. No production code changed in this checkpoint.
- 2026-07-01T15:04:13 main/working: Expanded audit in progress: derived 17 checklist items plus §11 deltas from the review doc. Current implementation evidence supports the code requirements; historical production subscriptions-row cleanup remains external/unverified from this worktree.
- 2026-07-01T15:09:04 main/working: Added dry-run-first stale tuition subscription cleanup utility for the review checklist's historical subscriptions-row cleanup item. The script selects only incomplete setup bookkeeping rows with no Stripe subscription id and requires --confirm-delete-stale-subscriptions with --apply. No production deletion was run.
- 2026-07-01T15:10:42 main/working: Remaining gate is explicit approval plus evidence for production data cleanup: run the utility first as dry-run with --expected-count 2 against the approved production DB, then rerun with --apply --confirm-delete-stale-subscriptions only after explicit destructive-operation approval.
## Verification

- No verification recorded yet.
- 2026-07-01T14:59:29: Focused evidence command passed: source backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_charge_autopay_use_case.py backend/v2/tests/application/test_webhook_handler.py::test_autopay_ach_payment_intent_processing_records_pending_attempt_only backend/v2/tests/application/test_webhook_handler.py::test_setup_intent_succeeded_completes_autopay_from_setup_metadata backend/v2/tests/application/test_webhook_handler.py::test_active_fallback_card_setup_does_not_mark_enrollment_active_or_default backend/v2/tests/application/test_reconcile_stripe_payment_intents.py backend/v2/tests/contract/test_invoice_numbering.py -q -> 60 passed in 2.82s
- 2026-07-01T15:04:13: Full backend DoD: source backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests -q from repo root -> 1 failed, 1993 passed, 5 warnings; failure is known cwd-path bootstrap test FileNotFoundError for v2/contexts/... path. Same test from backend/ passed: 1 passed in 0.42s.
- 2026-07-01T15:04:13: Backend lint/import gates passed: ruff check backend/v2 -> All checks passed; ruff format --check backend/v2 -> 757 files already formatted; lint-imports --config backend/pyproject.toml -> 4 contracts kept, 0 broken.
- 2026-07-01T15:04:13: Frontend focused UI gates passed: pnpm typecheck; pnpm lint exited 0 with 5 existing warnings; pnpm exec playwright test e2e/specs/billing-health.spec.ts -> 8 passed.
- 2026-07-01T15:09:04: Focused cleanup utility verification: RED first failed because scripts/dev/cleanup_stale_tuition_subscriptions.py did not exist; after implementation, PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_cleanup_stale_tuition_subscriptions.py -q -> 3 passed. ruff check and ruff format --check on the script/test passed.
- 2026-07-01T15:10:42: Non-destructive local cleanup dry-run passed: source backend/.venv/bin/activate && python scripts/dev/cleanup_stale_tuition_subscriptions.py --mongo-url mongodb://127.0.0.1:27017 --db-name academy_manager --expected-count 0 -> candidate_count 0, result dry_run. No writes performed.
## Reusable Lessons

- None recorded yet.
