# Production Launch Hardening Verification

Date: 2026-06-16

## Ship Verdict

Do not ship yet.

P0/P1 security hardening and ADR-0011 ledger-payment storage separation in this branch are code-complete and backend/frontend automated checks pass. Remaining ship blockers are operational/manual validation, target-environment migration execution, and money-flow reconciliation:

- Billing source-of-truth review found and this branch fixed the `LedgerPayment` shared-collection blocker. Ledger payments now write to `ledger_payments`; migration `0128_ledger_payments_storage` copy-only backfills old ledger-shaped rows; `backend/scripts/ledger_payments_storage_audit.py` provides dry-run/apply count evidence. Target-environment migration/reconciliation remains pending. See `docs/qa/2026-06-16-launch-readiness-addendum.md`.
- Production readiness items still need environment proof: backups, monitoring, audit log retention, rollback, secrets, CORS/cookie settings in deployed config.
- Full money-flow reconciliation still needs seeded/live-like flow validation across invoice, payment, credit, refund, payout, and Stripe webhook replay.

## P0 Verification

### 1. Tenant Context Composition

Issue: `settings.default_academy_id` could be used in request paths.
Old risk: requests, reports, artifacts, webhooks, or schedulers could touch the configured default academy instead of the authenticated/request tenant.
Files changed:

- `backend/v2/shared/config/settings.py`
- `backend/v2/shared/auth/middleware.py`
- `backend/v2/composition/parent.py`
- `backend/v2/composition/admin.py`
- `backend/v2/composition/coach.py`
- `backend/v2/main.py`

Fix summary: added launch-mode settings, configured Fly launch-mode env with `PRIMARY_ACADEMY_ID=acad_blno_badminton`, enforced `single_academy` tenant mismatch as 403, gated platform route mounting behind `ENABLE_PLATFORM_ROUTES`, added a production fail-closed settings guard for platform routes in single-academy launch mode, required explicit parent/webhook academy composition, made hardened admin closures use `current_academy_id()`, made coach metrics/attendance prefer request tenant, and changed scheduler fallback to runtime academy (`PRIMARY_ACADEMY_ID` when configured).
Follow-up fix: sidecar review found that non-SaaS `single_academy` request resolution still returned `settings.default_academy_id`, which would resolve `default-academy` and 403 production requests under the Fly launch env. `backend/v2/main.py` now derives a runtime academy id from `PRIMARY_ACADEMY_ID` in `single_academy` mode and uses it for request resolution, legacy membership fallback, parent composition, webhook composition, and public registration composition.
Test added: settings, tenant resolution, parent composition, admin composition tenancy, scheduler academy tests.
Command run: `cd backend && pytest v2/tests -q`
Result: latest full backend verification after follow-up fix: 1320 passed, 3 warnings.
Remaining risk: legacy/non-SaaS compatibility paths still intentionally reference `default_academy_id`; not a SaaS launch path.

### 2. Admin Analytics And Reports

Issue: admin reports/analytics could aggregate default academy data.
Old risk: admin could see or export data outside the request academy.
Files changed:

- `backend/v2/composition/admin.py`
- `backend/v2/interfaces/admin/reports_routes.py`
- `backend/v2/tests/unit/test_admin_composition_tenancy.py`
- `backend/v2/tests/interface/test_admin_analytics_routes.py`

Fix summary: attendance export, pending payments export, audit, invoice detail/artifacts, dues follow-up, and Phase 2 analytics use request tenant. CSV exports are allowlisted and admin-gated.
Test added: request-tenant regression tests for admin audit, invoices, artifacts, dues, attendance export, pending payments export, enrollment funnel, and route export authorization.
Command run: `pytest backend/v2/tests/interface/test_admin_analytics_routes.py backend/v2/tests/unit/test_admin_composition_tenancy.py -q`
Result: 23 passed.
Remaining risk: production report exports still need manual download QA.

### 3. Audit And Invoice Artifact Access

Issue: audit/invoice artifact helpers could read/write by default academy or unscoped identifiers.
Old risk: artifact reads/writes and audit listing could cross academy boundaries.
Files changed: `backend/v2/composition/admin.py`, `backend/v2/tests/unit/test_admin_composition_tenancy.py`.
Fix summary: audit list, invoice detail, invoice PDF/receipt artifact generation, and payment artifact fallback now include request academy filters.
Test added: tenant-scoped audit, invoice detail, invoice artifact, payment artifact tests.
Command run: included in admin composition tenancy suite.
Result: passed.
Remaining risk: artifact storage backend is still local/metadata-style; production storage permissions need operational review.

### 4. Stripe Customer Portal Lookup

Issue: portal lookup could fall back to global Stripe customer lookup by email.
Old risk: parent email collision could resolve another tenant customer.
Files changed: `backend/v2/composition/parent.py`, `backend/v2/tests/unit/test_parent_composition.py`.
Fix summary: portal uses stored tenant-scoped `stripe_customer_id` only; no global email lookup fallback.
Test added: parent composition tests.
Command run: focused hardening suite.
Result: 180 passed.
Remaining risk: production Stripe customer mappings should be spot-checked before launch.

### 5. Stripe Webhook Tenant Resolution

Issue: webhook composition/default metadata could mutate tenant data without persisted tenant-owned mapping.
Old risk: checkout/webhook events could update the wrong parent, subscription, payment, or autopay state.
Files changed:

- `backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py`
- `backend/v2/composition/parent.py`
- `backend/v2/main.py`
- `backend/v2/tests/application/test_webhook_handler.py`

Fix summary: checkout completion persists customer/autopay only when tenant-owned payment/subscription mappings exist; scheduler webhook processors are keyed by runtime academy.
Test added: metadata-only checkout completion does not mutate parent/autopay/payments/outbox; existing mapped subscription behavior remains covered.
Command run: backend v2 suite.
Result: 1201 passed, 3 warnings.
Remaining risk: live Stripe fixture replay against staging credentials still needed.

### 6. Coach Billing Moves Disabled

Issue: coach BFF exposed billing-impacting enrollment moves.
Old risk: coach could mutate billing enrollment state.
Files changed:

- `backend/v2/interfaces/coach/billing_enrollment_routes.py`
- `backend/v2/interfaces/coach/roster_routes.py`
- `backend/v2/tests/interface/test_coach_billing_enrollment_routes.py`
- `backend/v2/tests/interface/test_coach_roster.py`

Fix summary: coach billing move and roster add/remove mutations return 403 without calling use cases; coach read/preview flows remain.
Test added: route denial and no-mutation assertions.
Command run: focused hardening suite.
Result: 180 passed.
Remaining risk: frontend may still show disabled controls until UI cleanup.

## P1 Verification

### 7. Static Checks Include Composition Risk

Issue: static raw-Mongo guard excluded the riskiest composition files.
Old risk: hardened request paths could regress to default tenant silently.
Files changed: `backend/v2/tests/test_no_raw_tenant_mongo_access.py`.
Fix summary: added structural checks for hardened admin composition request paths and parent explicit academy composition.
Test added: static guard tests.
Command run: `pytest backend/v2/tests/test_no_raw_tenant_mongo_access.py backend/v2/tests/structural/test_saas_production_wiring.py -q`
Result: 17 passed.
Remaining risk: raw Mongo transitional exceptions still exist and are documented.

### 8. Enrollment Fallback Lookup

Issue: payment repo fallback enrollment lookup by enrollment ID lacked tenant filter.
Old risk: payment fallback could infer another tenant enrollment.
Files changed: `backend/v2/contexts/billing/infrastructure/mongo_payment_repo.py`, `backend/v2/tests/contract/test_mongo_payment_repo.py`.
Fix summary: fallback enrollment lookup includes `academy_id=current_academy_id()`.
Test added: cross-tenant enrollment row does not satisfy current tenant fallback.
Command run: `pytest backend/v2/tests/contract/test_mongo_payment_repo.py -q`
Result: 7 passed.
Remaining risk: none known for this path.

### 9. Platform Governance

Issue: support grant/revoke service allowed support role and revoke audit academy came from caller payload.
Old risk: direct use-case call could grant/revoke without platform admin, or produce misleading audit tenant.
Files changed:

- `backend/v2/contexts/platform/governance/application/use_cases.py`
- `backend/v2/contexts/platform/governance/infrastructure/mongo_governance_store.py`
- `backend/v2/tests/application/test_tenant_governance.py`
- `backend/v2/tests/interface/test_platform_governance_routes.py`

Fix summary: grant/revoke require `platform_admin` in the service, revoke is tenant-filtered in store, revoke audit uses stored grant academy, and platform route mounting is disabled when `ENABLE_PLATFORM_ROUTES=false`.
Test added: support-role denial, mismatched academy revoke regression, and `create_app()` route-registration coverage for platform routes on/off.
Command run: governance app/interface tests; `source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && pytest backend/v2/tests/unit/test_healthz.py backend/v2/tests/unit/test_settings.py -q`.
Result: governance tests passed; route/settings suite passed with 17 tests.
Remaining risk: deployed Fly env must be verified to confirm `ENABLE_PLATFORM_ROUTES=false` and `PRIMARY_ACADEMY_ID=acad_blno_badminton` are active.

### 10. Coach Roster Permissions

Issue: coach roster add/remove conflicted with launch permission matrix.
Old risk: coach could alter roster membership.
Files changed: coach roster route/tests.
Fix summary: add/remove return 403.
Test added: route denial/no mutation.
Command run: focused hardening suite.
Result: 180 passed.
Remaining risk: frontend cleanup only.

### 11. Public Registration

Issue: public registration created active SaaS parent membership.
Old risk: public user could self-authorize into a tenant.
Files changed:

- `backend/v2/contexts/identity/application/use_cases/register_public_parent.py`
- `backend/v2/tests/application/test_register_public_parent.py`

Fix summary: SaaS self-registration creates only `invited` membership if none exists; existing active membership is preserved; invited/suspended/removed membership is not reactivated.
Test added: invited-only creation, existing active unchanged, inactive not reactivated.
Command run: registration app/interface/rate-limit tests.
Result: 22 passed.
Remaining risk: admin approval flow may need to activate invited parent membership as part of product workflow.

### 12. Admin Exports

Issue: exports lacked explicit report allowlist.
Old risk: unknown report names returned a downloadable CSV error artifact and future unguarded reports could be exposed.
Files changed: `backend/v2/interfaces/admin/reports_routes.py`, `backend/v2/composition/admin.py`.
Fix summary: route allowlist for `pending-payments`, `revenue`, `attendance`; composition raises for unknown report.
Test added: known export allowed, unknown rejected without calling use case, non-admin denied.
Command run: admin analytics and composition tests.
Result: 23 passed.
Remaining risk: manual browser download/export QA still needed.

## Verification Commands

- `cd backend && pytest v2/tests -q` before ADR-0011 split -> 1196 passed.
- `source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && pytest backend/v2/tests/unit/test_healthz.py backend/v2/tests/unit/test_settings.py -q` after platform route gating -> 17 passed.
- `source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && pytest backend/v2/tests/unit/test_settings.py backend/v2/tests/interface/test_admin_analytics_routes.py backend/v2/tests/unit/test_admin_composition_tenancy.py -q` after platform fail-closed guard and invoice-line metadata -> 37 passed.
- `cd backend && ruff check v2 && ruff format --check v2` -> passed.
- Backend pre-push-equivalent before ADR-0011 split: `pytest v2/tests -n auto -q --tb=short` -> 1196 passed.
- Frontend node unit tests -> 32 passed.
- `pnpm typecheck` -> passed.
- `pnpm lint` -> passed with 5 warnings.
- `cd frontend && pnpm typecheck && pnpm lint && pnpm exec playwright test e2e/specs/admin-students.spec.ts --project=chromium-mobile` after Student Billing read-only invoice breakdown -> typecheck passed, lint passed with 5 existing warnings, focused E2E 4 passed.
- `pnpm e2e` -> 164 passed, 30 skipped.
- Direct isolated local-auth probe against `http://127.0.0.1:9109`, `http://127.0.0.1:8011/api/v2/me`, and `http://localhost:3011/api/v2/me` -> emulator sign-in ok, backend `/me` 200, frontend proxy `/me` 200.
- Isolated seeded local-auth browser suite: `LOCAL_AUTH_E2E=1 LOCAL_AUTH_BASE_URL=http://localhost:3011 pnpm e2e:local-auth` -> 7 passed.
- ADR-0011 focused billing/webhook suite -> 42 passed.
- `cd backend && pytest v2/tests -q` after platform fail-closed guard and Student Billing read-only metadata slice -> 1201 passed, 3 warnings.
- `cd backend && ruff check v2 scripts/ledger_payments_storage_audit.py && ruff format --check v2 scripts/ledger_payments_storage_audit.py` after ADR-0011 split -> passed.
- `git diff --check` -> passed.

## Skipped Or Blocked

- `scripts/dev/pre-push-checks.sh` wrapper: initially failed because this worktree had no local `backend/.venv`; equivalent commands passed using the main checkout backend venv. A worktree-local `.venv` symlink was used for local-stack validation only and is not part of the code changes.
- `scripts/local_test_stack.sh all`: initially failed because this worktree had no local `backend/.venv`; later local-auth validation used an isolated stack on Mongo `27018`, Firebase Auth `9109`, backend `8011`, frontend `3011`, and DB `academy_manager_launch_hardening`.
- Local stack operational note: one malformed retry ran `scripts/local_test_stack.sh fresh` against the default local stack and reseeded the default local database before being stopped. The final validation was rerun on the isolated stack, and all local test ports were verified stopped afterward.
- Stripe live/staging webhook replay was not run. The branch has unit/contract coverage for tenant-owned mappings and metadata-only rejection, but live-like Stripe fixture replay remains required.
- Billing-convergence route inspection found the historical remove-line/void-invoice route hazards are not active in this worktree. Student Billing now has a read-only invoice breakdown using the tenant-scoped invoice detail endpoint; the remaining billing launch gap is missing admin billing action workflows and target-environment money-flow reconciliation.
- Security sidecar read-only review found no residual code-level P0/P1 launch security issue in the current diff for tenant leaks, RBAC, platform routes, Stripe tenant resolution, public registration abuse, exports/artifacts leakage, or `default_academy_id` misuse. It still requires deployed env verification for launch flags.

## Deferred Items

- Owner role implementation.
- Student login.
- Full platform operator workflow.
- Multi-academy tenant lifecycle.
- Tenant deletion/export tooling.

## Manual QA Needed

- Parent payment, refund/credit, invoice generation, payment allocation, coach payout.
- Admin reports CSV download inspection.
- Mobile parent/coach flows and desktop admin flows against a seeded stack.
- Production environment verification for secrets, CORS, cookies, backups, logging, monitoring, and rollback.

## Migration Needed

Migration `0128_ledger_payments_storage` was added for the ADR-0011 ledger-payment split. Run `backend/scripts/ledger_payments_storage_audit.py` against the target database in dry-run mode, then apply the copy-only migration with operator approval. Existing active public-registration memberships are not backfilled; decide whether to audit/downgrade any pre-launch self-created active parent memberships.

## Rollback Notes

This branch is mostly authorization/tenant-scope hardening. Rollback would restore prior unsafe behaviors; prefer forward fixes if any UI workflow depends on disabled coach mutations or invited public memberships.
