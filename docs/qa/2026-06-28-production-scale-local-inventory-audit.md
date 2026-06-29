# Production-Scale Local Inventory Audit

Date: 2026-06-28

## Goal

Build sanitized, production-scale local data under production-like settings; inventory
every user-facing route and high-risk workflow; test as real users; log bugs with
evidence; fix shared causes with regression tests; rerun until clean or blocked.

## Current Behavior Found

- The canonical frontend has 63 app routes across public/auth, admin, coach,
  parent, shared authenticated shells, and the local API proxy. The inventory
  manifest is now checked against `frontend/app/**/{page.tsx,route.ts}`.
- Most Playwright E2E uses mocked APIs and `NEXT_PUBLIC_E2E_AUTH_BYPASS=1`.
  `local-auth-qa.spec.ts` is the only real seeded-auth browser suite.
- The safest production-like local environment is Docker SaaS staging:
  `scripts/dev/saas_staging.sh up`, `blno-seed`, `smoke`.
- Existing BLNO local seed is realistic but not production-scale: 36 parent
  accounts, 46 students, 4 sessions, 3 billing months, attendance, pathway, and
  billing ledger data.
- There was no production-data sanitizer and no bulk synthetic scale generator.
  The audit must not use real production data or secrets.

## Files Affected

- `scripts/dev/scale_blno_staging.py`
- `scripts/dev/export_local_auth_inventory_env.py`
- `backend/v2/tests/unit/test_blno_scale_seed.py`
- `backend/v2/tests/unit/test_local_auth_inventory_env_export.py`
- `backend/v2/tests/unit/test_audit_inventory_manifest.py`
- `backend/v2/tests/unit/test_local_auth_inventory_spec.py`
- `frontend/e2e/specs/local-auth-inventory.spec.ts`
- `frontend/playwright.local-auth.config.ts`
- `docs/qa/2026-06-28-production-scale-local-inventory-audit.md`
- `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`
- `docs/test-results/active/2026-06-28-production-scale-local-full-inventory-audit.md`

## Proposed Approach

1. Use Docker SaaS staging for production-like local settings: SaaS mode,
   Firebase Auth emulator, local Mongo, email disabled, localhost CORS, and
   optional Stripe test-mode only.
2. Seed BLNO realistic local data, then preview deterministic synthetic scale
   data with `scripts/dev/saas_staging.sh scale`; after explicit approval for
   local data mutation, apply it with `scripts/dev/saas_staging.sh scale --apply`.
3. Run real-auth audit flows from seeded accounts. Use mocked E2E only as
   supplementary route/control coverage, not as proof of real-user behavior.
4. For each bug, record reproduction evidence, find root cause, add regression
   coverage, implement the narrow fix, and rerun the affected workflow.
5. Rerun the inventory matrix after fixes. Stop only at clean pass or a blocked
   handoff with exact blockers.

## Risks

- Running `seed`, `blno-seed`, `reset`, `nuke`, or `local_test_stack.sh fresh`
  modifies local Mongo/Firebase emulator data and needs explicit approval.
- Local Docker staging cannot prove DNS, TLS, secure cookies, HSTS/CSP,
  managed Mongo backup/restore, external alerting, or real Firebase token
  signature behavior.
- Stripe testing must use test-mode keys only. Live keys are out of scope.
- Synthetic scale rows are suitable for local load/UX/data-shape testing, not
  as proof that production data migration has been sanitized.

## Verification Plan

Baseline:

- `backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_settings.py -q`
- `cd frontend && pnpm install --frozen-lockfile`
- `backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_blno_scale_seed.py -q`
- `backend/.venv/bin/ruff format --check scripts/dev/scale_blno_staging.py backend/v2/tests/unit/test_blno_scale_seed.py`
- `backend/.venv/bin/ruff check scripts/dev/scale_blno_staging.py backend/v2/tests/unit/test_blno_scale_seed.py`

Local environment, after approval for local data mutation:

- `scripts/dev/saas_staging.sh up`
- `scripts/dev/saas_staging.sh blno-seed`
- `backend/.venv/bin/python scripts/dev/scale_blno_staging.py --parents 250 --students-per-parent 2`
- `scripts/dev/saas_staging.sh scale --parents 250 --students-per-parent 2`
- `scripts/dev/saas_staging.sh scale-safety --parents 250 --students-per-parent 2`
  to validate the synthetic dry-run plan is local-only, sanitized, tenant-scoped,
  relationship-consistent, and safe to clean up before any apply step.
- After explicit local data mutation approval:
  `scripts/dev/saas_staging.sh scale --apply --parents 250 --students-per-parent 2`
- To inspect synthetic scale rows before cleanup:
  `scripts/dev/saas_staging.sh scale --cleanup`
- After explicit local destructive-action approval, remove only generated scale
  rows with `scripts/dev/saas_staging.sh scale --cleanup --apply`.
- `eval "$(scripts/dev/saas_staging.sh local-auth-env)"` to populate
  dynamic route IDs for the real-auth Playwright inventory.
- `scripts/dev/saas_staging.sh audit-readiness` to run read-only checks for
  local base URL, dynamic route IDs, existing synthetic scale rows, and the
  latest Playwright evidence report before starting the real-user inventory.
  Readiness also blocks if `LOCAL_AUTH_E2E=1` or any admin, coach, or parent
  local-auth credentials are missing from the shell environment.
- `scripts/dev/saas_staging.sh audit-static-gaps --fail-on-gaps` to confirm
  route source files do not expose obvious controls or state branches missing
  from the manifest/checklist.
  The report also lists potential control undercounts as non-fatal warnings;
  those are review queues for dense pages where source evidence lines exceed
  named manifest controls and need manual real-user confirmation.
- `scripts/dev/saas_staging.sh audit-acceptance` to list routes and global
  surfaces whose acceptance criteria are fewer than their workflows or risk
  edges. Treat findings as documentation gaps to resolve before claiming a
  clean full inventory.
- `scripts/dev/saas_staging.sh audit-control-evidence` to render direct
  source evidence for route-owned buttons, inputs, and modals. Use it as a
  reconciliation aid for dense pages during the approved real-user pass.
- `scripts/dev/saas_staging.sh audit-gate` to aggregate the read-only gates
  into `CLEAN_PASS`, `READY_WITH_WARNINGS`, or `BLOCKED`. A clean pass requires
  applied production-scale synthetic rows, dynamic route IDs, clean static and
  acceptance reports, a Playwright report containing the full manifest-derived
  inventory test set, and no Playwright failures or skips.
- `scripts/dev/saas_staging.sh audit-artifacts` to write the local Markdown
  handoff bundle: readiness report, inventory matrix, static gap report,
  acceptance coverage report, source control evidence report, aggregate audit
  gate, execution checklist, test summary, and index under the evidence
  directory. The artifact command reports both readiness and aggregate gate
  results and exits non-zero until the aggregate gate is `CLEAN_PASS`.
- `scripts/dev/saas_staging.sh smoke --slug blno --domain blno.localhost`
- `scripts/dev/saas_staging.sh audit blno`

Browser and real-user audit:

- Admin, coach, and parent login through Firebase emulator, no auth bypass.
- `cd frontend && LOCAL_AUTH_E2E=1 ... pnpm e2e:local-auth` now defaults to
  `http://blno.localhost:3000` and includes `local-auth-qa.spec.ts` plus
  `local-auth-inventory.spec.ts`.
- The local-auth inventory currently expands to 72 Playwright tests: one test
  per directly navigable static manifest route, one skipped-until-configured
  test per dynamic manifest route, plus the existing focused defect checks.
  The aggregate gate validates that the JSON report includes every expected
  manifest inventory test, so a filtered or partial Playwright run cannot
  satisfy the clean-pass criteria.
- Dynamic manifest routes such as `/admin/sessions/[id]` and
  `/coach/students/[studentId]/passport` require seeded ID substitutions from
  the approved local BLNO seed/scale run before their Playwright checks execute.
  The local-auth Playwright spec uses an exact route-to-env-var contract for
  every non-proxy dynamic manifest route; broad prefix matching is intentionally
  disallowed so future dynamic routes cannot be covered accidentally.
  Required env vars are `LOCAL_AUTH_ADMIN_SESSION_ID`,
  `LOCAL_AUTH_ADMIN_STUDENT_ID`, `LOCAL_AUTH_ADMIN_USER_ID`,
  `LOCAL_AUTH_ADMIN_PAYOUT_ID`, `LOCAL_AUTH_ADMIN_APPLICATION_ID`,
  `LOCAL_AUTH_ADMIN_WAIVER_ID`, `LOCAL_AUTH_ADMIN_WAIVER_SIGNATURE_ID`,
  `LOCAL_AUTH_ADMIN_PROGRAM_ID`, `LOCAL_AUTH_COACH_OCCURRENCE_ID`,
  `LOCAL_AUTH_COACH_SESSION_ID`, `LOCAL_AUTH_COACH_SESSION_DATE`, and
  `LOCAL_AUTH_COACH_STUDENT_ID`. Generate currently available values with
  `scripts/dev/saas_staging.sh local-auth-env`; it prints comments for IDs
  that are still missing from the local staging dataset.
- Real-auth Playwright execution also requires `LOCAL_AUTH_E2E=1` and
  `LOCAL_AUTH_ADMIN_EMAIL`, `LOCAL_AUTH_ADMIN_PASSWORD`,
  `LOCAL_AUTH_COACH_EMAIL`, `LOCAL_AUTH_COACH_PASSWORD`,
  `LOCAL_AUTH_PARENT_EMAIL`, and `LOCAL_AUTH_PARENT_PASSWORD`.
- Each inventory route test fails on framework errors, browser console/page
  errors, failed `/api/*` requests, and `/api/*` responses with HTTP 500+.
  Passing route tests attach a full-page screenshot to the Playwright JSON
  report artifacts so the audit has positive evidence, not only failure
  evidence.
- `blno-seed` does not by itself guarantee payout period, registration
  application, waiver template, or waiver signature detail IDs. The synthetic
  `scale` step now adds sanitized fixture rows for those dynamic detail pages;
  if `local-auth-env` still prints a missing ID, that route remains skipped
  until the corresponding local workflow creates the record.
- Confirmed bugs are logged in
  `docs/qa/2026-06-28-production-scale-local-bug-log.md`.
- Evidence directory: `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/`.
- Playwright writes run artifacts to
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-artifacts`,
  JSON results to
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-report.json`,
  and the HTML report to
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-html`.
- Capture screenshot/trace/video/log excerpt for each failed workflow.

## Acceptance Criteria

- Local dataset contains BLNO realistic seed plus deterministic synthetic scale
  rows for at least 250 parents, 500 students, 500 enrollments, 1,500 invoices,
  one payout period, one pending onboarding application, one waiver template,
  one waiver signature, and a mixed open/paid ledger state.
- The synthetic scale plan passes `scale-safety` before any scale rows are
  applied; validator output must report `mongo_touched: false`.
- Every route in the inventory below is opened as an authorized user or verified
  as intentionally blocked for that role.
- Every route has loading, empty, error, and primary-action behavior assessed
  where the UI exposes those states.
- Money workflows preserve billing safety rules: ledger state is authoritative,
  redirects do not prove payment, duplicate payment actions do not double-pay,
  failed attempts do not close invoices, and webhook/retry failures remain
  visible.
- Every confirmed bug has reproduction evidence, a root-cause note, regression
  coverage where practical, and a rerun result.
- Final handoff states commands run, results, skipped checks, and remaining
  risks. No production systems, sensitive data, destructive operations, live
  Stripe keys, or real email sends are used without explicit approval.

## Route Inventory

Machine-readable route/control/state coverage lives in
`docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`.
Generate a reviewable role and route matrix with:

```bash
backend/.venv/bin/python scripts/dev/summarize_inventory_manifest.py \
  --output /tmp/academy-manager-local/evidence/20260628-production-scale-audit/inventory-coverage-matrix.md
```

Generate the real-user execution checklist with:

```bash
backend/.venv/bin/python scripts/dev/generate_inventory_checklist.py \
  --output /tmp/academy-manager-local/evidence/20260628-production-scale-audit/inventory-checklist.md
```

Public/auth:

- `/login`: email/password, Google sign-in, forgot password, alerts, loading,
  email verification resend.
- `/register`: parent registration start/continue, Firebase user creation,
  backend registration failure recovery.
- `/post-login`: persona redirect, no-role state, slow `/me`, stale session.
- Public legal/marketing: `/`, `/privacy`, `/terms`, `/security`.

Admin:

- `/admin`, `/admin/dashboard`: KPI cards, attention cards, revenue/recent
  payments, partial API failure.
- `/admin/sessions`, `/admin/sessions/[id]`, `/admin/sessions/[id]/skill-board`:
  table/calendar, create/edit/cancel, roster add/remove/pause/resume/transfer,
  waitlist promote/skip/remove, replacement coach, teaching plan, skill board.
- `/admin/students`, `/admin/students/[studentId]`,
  `/admin/students/[studentId]/progress`: search/filter/pagination, detail tabs,
  edit, parent reassignment, billing modals, discounts, invoice lines, manual
  payment, send/void/autopay.
- `/admin/users`, `/admin/users/[userId]`, `/admin/coaches`, `/admin/parents`:
  directory filters, create user, duplicate email, invalid role, detail load.
- `/admin/payments`, `/admin/billing-health`, `/admin/dues`: generate monthly,
  sync/reconcile, refunds, mark/undo paid, attempts, webhook retry/replay, dues
  reminders.
- `/admin/expenses`, `/admin/payouts`, `/admin/payouts/[payoutId]`,
  `/admin/session-economics`, `/admin/reports`, `/admin/coach-payslip`:
  expense CRUD, payout generate/approve/reopen/paid/export/correction, reporting.
- `/admin/registrations`, `/admin/registrations/[applicationId]`,
  `/admin/waitlist`: approval/rejection/waitlist actions and conflict states.
- `/admin/waivers`, `/admin/waivers/[waiverId]`,
  `/admin/waivers/signatures/[signatureId]`: draft/publish/require/signature
  detail, obsolete waiver states.
- `/admin/pathway`, `/admin/pathway/[programId]`, `/admin/pathway/progress`,
  `/admin/level-up-queue`: program edits, progress, approve/reject with reason.
- `/admin/messages`, `/admin/settings`, `/admin/audit-logs`: composer/settings
  save/audit pagination and error states.

Coach:

- `/coach/dashboard`: date controls, session cards, prepare/skill/passport
  links, placeholder actions.
- `/coach/today`: previous/today/next, loading/error/empty/refreshing.
- `/coach/sessions`, `/coach/sessions/[id]`: schedule, attendance present/absent,
  late-state coverage, note mutation, stale occurrence id.
- `/coach/sessions/[id]/skills`, `/coach/sessions/[id]/progress`,
  `/coach/students/[studentId]/passport`, `/coach/today/plan`: skill status
  updates, teaching plan outcomes, unplaced students, external video links.
- `/coach/profile`, `/coach/needs-review`: edit/save/cancel, failed mutation
  tray, dismiss/export.

Parent:

- `/parent/dashboard`: child switcher, add child, metrics, next class, issue strip.
- `/parent/onboarding`: parent info, child info, waiver, session selection, quote,
  checkout redirect, resume after tab close.
- `/parent/checkout/return`: terminal/nonterminal polling, missing application id.
- `/parent/payments`: portal, autopay, invoice/balance pay, credits, pause request,
  history, selected invoice 404/conflict.
- `/parent/waivers`: per-child status, signer input, outdated vs pending states.
- `/parent/children`, `/parent/attendance`, `/parent/progress`: child cards,
  attendance history, progress overview/passport/resources.

Shared:

- `/calendar`, `/messages`: role-specific data visibility, empty/error states.
- `/api/v2/[...path]`: proxy methods, auth bridge headers, upstream error/redirect
  behavior, tenant host behavior.

## Finite Edge-Case Set

- Wrong-role access: parent to admin/coach, coach to admin/parent, admin to
  parent/coach when not multi-role.
- Tenant host mismatch, missing tenant, internal tenant header mismatch.
- Firebase token valid but app membership suspended/removed.
- `/me` 401, 403, and 500 after visible login success.
- Double-click money actions and duplicate webhook events.
- Open invoice with failed payment attempt; paid invoice double-pay attempt.
- Stripe test/live mode mismatch, webhook signature rejection, replay failure.
- Empty datasets after scale seed: no sessions, no students, no invoices, no waivers.
- Pagination/search with scale data.
- Date/timezone boundaries around June 2026 month end and recurring sessions.
- Offline/slow network for coach attendance and parent onboarding/payment return.
- Email delivery disabled: UI must not claim real email sent.
