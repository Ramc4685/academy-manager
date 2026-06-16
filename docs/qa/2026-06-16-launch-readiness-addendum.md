# Launch Readiness Addendum

Date: 2026-06-16

## Verdict

Do not ship yet.

Security, RBAC, tenant-isolation P0/P1 hardening, and ADR-0011 ledger-payment
storage separation are code-complete in this branch and have automated
evidence. The remaining blockers are now production execution/validation gates:
run the copy-only ledger-payment migration in the target environment, reconcile
money flows, prove production operations, and complete live-like QA.

## Shipping Rule Status

| Gate | Status | Evidence / gap |
| --- | --- | --- |
| No tenant leaks | Green for hardened v2 paths | Backend v2 suite passed; focused tenant/RBAC tests passed; local-auth parent/admin/coach browser suite passed; collection-level audit in `docs/qa/2026-06-16-tenant-isolation-audit.md`; non-SaaS `single_academy` requests now resolve `PRIMARY_ACADEMY_ID` instead of `default_academy_id`; invoice email delivery verifies active parent membership in the request academy before reading global user email. |
| No RBAC gaps | Green for reviewed P0/P1 paths | Coach billing moves and roster mutations now deny; admin exports are allowlisted; platform governance requires platform admin; platform routes are not mounted when `ENABLE_PLATFORM_ROUTES=false`. |
| Money flows reconcile | Yellow | ADR-0011 code now writes `LedgerPayment` to `ledger_payments` and includes a copy-only migration. The migration has not been run against the target environment and full invoice/payment/credit/refund/payout reconciliation has not been run. |
| Parent/coach flows pass mobile | Partial green | `pnpm e2e:local-auth` passed on mobile Chromium against seeded local stack. Broader real-device/mobile browser QA is still manual. |
| Admin flows pass desktop | Partial green | Mocked E2E and local-auth admin checks pass. Student Billing invoice actions are now integrated from `feat/billing-ledger-convergence` and covered by focused unit/interface tests plus the admin-students mobile E2E render path; admin export/download and live billing action workflows still need manual desktop QA. |
| Stripe webhooks are idempotent | Backend green, staging pending | `stripe_webhook_events` dedup and metadata-only rejection tests pass. Stripe fixture replay against staging/live-like config is still required. |
| Backups and rollback exist | Red | Documented in `DEPLOYMENT.md`, but no restore-drill evidence or rollback rehearsal is present in this branch. |

## RBAC Permission Matrix

| Action | Public | Parent | Coach | Admin | Owner | Platform Operator | Student future |
| --- | --- | --- | --- | --- | --- | --- | --- |
| View | Marketing/register only | Own child, own payments, own progress, own messages | Assigned sessions/students, own payout | Academy-wide operational views | Proposed; disabled by `ENABLE_OWNER_ROLE=false` | Platform/governance views only if platform routes enabled | Proposed; disabled by `ENABLE_STUDENT_LOGIN=false` |
| Create | Public registration application only | Own onboarding, checkout/autopay, pause request | Attendance/progress for assigned sessions/students | Sessions, enrollments, invoices, users, reports | Proposed | Platform tenant/support records only if enabled | No current access |
| Edit | No | Own profile/onboarding/contact details | Assigned attendance/progress only | Academy-scoped admin records and billing workflows | Proposed | Platform governance only if enabled | No current access |
| Delete | No | No hard delete | No roster/billing deletes | Limited operational void/disable; hard delete not a launch feature | Proposed | Tenant deletion/export tooling deferred | No current access |
| Approve | No | No | No | Registration/enrollment/billing/pause workflows as implemented | Proposed | Support/governance approval only if enabled | No current access |
| Export | No | No | No | Tenant-scoped allowlisted reports only | Proposed | Platform export tooling deferred | No current access |

## Billing Source Of Truth

| Area | Current source | Status | Notes |
| --- | --- | --- | --- |
| Invoice | `invoices` + `invoice_lines` via `MongoBillingLedgerRepository` | Implemented, validation pending | Intended source of truth per `docs/plans/2026-06-14-billing-ledger-convergence.md`; the integration branch includes Student Billing actions for create invoice, add/remove line, send invoice, charge autopay, record manual payment, and void safeguards. Refund/credit convergence and live reconciliation remain pending. |
| Payment | Legacy `Payment` in `payments`; `LedgerPayment` in `ledger_payments` | Code fixed, migration pending | `mongo_billing_ledger_repo.py` now reads/writes ledger payments from `ledger_payments`. Migration `0128_ledger_payments_storage` creates indexes and copy-only backfills ledger-shaped rows from `payments`; `backend/scripts/ledger_payments_storage_audit.py` provides dry-run/apply count evidence. |
| Credit | `account_credit_ledger` | Backend implemented | Used by ledger allocation and withdrawal-credit paths; full reconciliation still pending. |
| Refund | Stripe refund + local payment/credit records | Partially implemented | `IssueRefund` exists; ledger refund/credit-note convergence is not fully proven end to end. |
| Payout | `payout_periods`, `payout_period_lines`, `payout_audit_log` | Backend implemented | Requires manual/admin workflow QA and payout reconciliation before ship. |
| Stripe webhook idempotency | `stripe_webhook_events` | Backend implemented | Tests pass; staging fixture replay remains required. |

## Production Readiness

| Item | Status | Evidence / gap |
| --- | --- | --- |
| Deployment environment | Partial | `DEPLOYMENT.md` documents Fly backend and Cloudflare frontend. `backend/fly.toml` now sets launch-mode env defaults, but actual deployed env values were not inspected. |
| Secrets handling | Partial | Required secrets are documented. Live secret presence/rotation cannot be verified from code. |
| CORS settings | Partial | `backend/fly.toml` and `DEPLOYMENT.md` use explicit origins; deployed config still needs confirmation. |
| Cookie settings | Partial | `COOKIE_SECURE=true` documented and in Fly config; deployed behavior still needs browser check. |
| Auth provider config | Partial | Firebase production requirements documented; authorized domains and first-party auth proxy need production confirmation. |
| Database backups | Red | Backup/restore drill is documented but not evidenced. |
| Error logging | Partial | Structured logging exists; external log drain/alert rules not proven. |
| Audit logs | Partial | Platform/admin audit persistence exists and tenant fixes are tested; retention and operational review are pending. |
| Monitoring | Red | Health endpoint exists; external monitors/alerts not proven. |
| Rollback plan | Partial | Deployment docs contain rollback notes; no rehearsal evidence. |
| Migration safety | Yellow | Copy-only ADR-0011 migration is implemented and tested. Target-environment dry-run/reconciliation and any later cleanup still need operator approval. |

## Core Flow Test Status

| Flow | Status |
| --- | --- |
| Public registration | Backend tests pass; full browser/admin approval path still needs workflow QA. |
| Parent onboarding | Local-auth browser path passed. |
| Parent payment | Pending full live-like Stripe/fake-gateway flow. |
| Admin approval | Pending full registration approval workflow QA. |
| Enrollment creation | Covered by backend tests; end-to-end payment-to-enrollment flow still pending. |
| Session occurrence creation | Covered by backend tests; manual admin workflow QA pending. |
| Coach today view | Local-auth browser path passed. |
| Attendance submission | Backend tests pass; browser workflow QA pending. |
| Skill progress update | Mocked E2E previously passed; seeded browser workflow QA pending. |
| Invoice generation | Backend/UI workflow integrated; target migration/reconciliation and manual admin QA pending. |
| Payment allocation | Backend tests pass for ledger allocation and manual/autopay payment paths; full reconciliation pending. |
| Refund / credit | Backend tests exist; full reconciliation pending. |
| Coach payout | Backend tests exist; admin workflow and payout reconciliation pending. |
| Parent pause request | Browser/admin workflow QA pending. |
| Admin reports export | Tenant/export tests pass; manual CSV download inspection pending. |

## Known Bugs / Blockers

| Bug | Severity | Role | Page | Status |
| --- | ---: | --- | --- | --- |
| Ledger payments shared `payments` collection with legacy payments, despite ADR-0011 requiring `ledger_payments`. | P1 launch blocker | Admin / Parent | Billing | Fixed in branch; target migration pending |
| Non-SaaS `single_academy` launch config resolved `default-academy`, causing request-path default tenant use and production 403s when `PRIMARY_ACADEMY_ID=acad_blno_badminton`. | P0 launch blocker | All authenticated roles | All v2 routes | Fixed in branch; regression proves primary academy resolution |
| Full money-flow reconciliation not run across invoice, payment, credit, refund, payout, and Stripe webhook replay. | P1 launch blocker | Admin / Parent | Billing | Open |
| Production backup/restore, monitoring, log drain, secrets, and rollback proof missing. | P1 launch blocker | Platform Operator | Operations | Open |
| Admin student Billing tab convergence workflow requires live-like validation after merge. | P1 launch blocker | Admin | Student Billing | Integrated from `feat/billing-ledger-convergence`: create invoice, add/remove charge, generate invoice Stripe checkout URL when configured, gated Resend invoice email delivery when configured, charge autopay, record manual payment, void safeguards, invoice lines, totals, allocations, credits. Remaining: live Stripe webhook/Resend/PDF behavior, refund/credit workflow, reconciliation, and manual desktop QA. |
| Local stack helper requires care in this Codex exec environment because infra processes can be reaped when the command exits. | P2 | Developer | Local QA | Documented |

## ADR-0011 Implementation Evidence

- `MongoBillingLedgerRepository` stores ledger payments in `ledger_payments`.
- Migration `0128_ledger_payments_storage` creates `ledger_payments` indexes and
  copy-only backfills ledger-shaped rows from `payments`.
- Script `backend/scripts/ledger_payments_storage_audit.py` reports dry-run
  counts and can explicitly apply the copy-only migration with `--apply`.
- Regression tests prove normal legacy `payments` rows cannot satisfy ledger
  allocation, ledger payments are not inserted into `payments`, and migration is
  idempotent/copy-only. The audit script count path is covered by the same
  regression.
- Verification: focused billing/webhook suite passed, full backend v2 suite
  passed, backend ruff check/format passed.

## Launch Mode Evidence

- `backend/fly.toml` sets `APP_TENANCY_MODE=single_academy`, `PRIMARY_ACADEMY_ID=acad_blno_badminton`, `ENABLE_PLATFORM_ROUTES=false`, `ENABLE_OWNER_ROLE=false`, and `ENABLE_STUDENT_LOGIN=false`.
- Non-SaaS `single_academy` request resolution uses `PRIMARY_ACADEMY_ID`, so launch mode does not require `V2_SAAS_MODE=true` or `V2_DEFAULT_ACADEMY_ID=acad_blno_badminton` to avoid `default-academy`.
- `backend/v2/main.py` mounts platform routes only when `settings.enable_platform_routes` is true.
- Production `single_academy` settings fail closed if `ENABLE_PLATFORM_ROUTES=true`.
- Unit coverage proves platform routes are mounted by default and absent when `ENABLE_PLATFORM_ROUTES=false`.
- Operator check before deploy: confirm deployed Fly secrets/env do not override these launch-mode values unexpectedly and authenticated `/api/v2/me` returns `academy_id=acad_blno_badminton` for the production host.

## Billing Workflow Integration Evidence

- This integration branch merges the billing convergence workflow from `feat/billing-ledger-convergence`.
- Backend routes now exist for product listing, create invoice, add/remove invoice lines, send invoice, charge autopay, record manual payment, and void invoice safeguards. The send-invoice route now injects the Stripe gateway and returns a checkout URL when Stripe is configured; it injects a Resend-backed invoice email adapter only when email delivery is enabled and verifies active parent membership in the request academy before reading the global user email. It does not mark delivery as `sent` unless email delivery succeeds.
- The old plan warnings about `remove_invoice_line` using `ledger._db` directly and `void_invoice_route` hardcoding the reason are no longer current on this branch: remove-line uses `RemoveInvoiceLine`, and void requires `VoidInvoiceRequest.reason`.
- The Student Billing tab now renders invoice totals, line metadata, allocations, credits, and action controls for add charge, send, autopay, record payment, create invoice, and void.
- The launch blocker is no longer the absence of the admin billing workflow code. It is proving that workflow in a live-like environment: target migration/reconciliation, Stripe webhook/Resend/PDF behavior, refund/credit handling, and manual desktop QA.

## Next Launch Slice

Run the operator checklist in `docs/runbooks/production-launch-hardening.md`.
At minimum:

1. Run `backend/scripts/ledger_payments_storage_audit.py` against a
   staging/prod-like database in dry-run mode, then with `--apply`, and save the
   before/after count reconciliation output. Do not delete old `payments` rows
   in this slice.
2. Run end-to-end billing reconciliation: invoice generation, payment
   allocation, refund/credit, Stripe webhook replay, and coach payout.
3. Complete admin desktop QA for the merged Billing tab actions: create invoice, add/remove charge, send invoice, charge autopay, record manual payment, void, refund/credit, and delivery status. Include a staging Resend check proving email delivery changes `delivery_status` to `sent`, and disabled/misconfigured email leaves delivery as `not_sent` or `delivery_failed`.
4. Prove production operations: secrets, CORS/cookies, backups/restore drill,
   log drain, monitoring alerts, and rollback rehearsal.
