# Production-Scale Local Audit Bug Log

Date: 2026-06-28

Status: Fixes implemented and verified in full local real-user rerun

Known bugs: 4

This file records confirmed user-facing defects found during the production-scale
local audit. Every bug must include reproduction evidence before it can be
treated as confirmed. Suspicions, flaky observations, or one-off console noise
belong in the active test ledger until reproduced.

## Evidence Directory

Use:

```txt
/tmp/academy-manager-local/evidence/20260628-production-scale-audit/
```

Recommended artifact names:

```txt
BUG-001-admin-payments-double-click.png
BUG-001-admin-payments-double-click.trace.zip
BUG-001-admin-payments-double-click.webm
BUG-001-backend.log
```

Playwright local-auth inventory runs also write:

```txt
playwright-artifacts/
playwright-report.json
playwright-html/
```

Generate a triage summary from the JSON report:

```bash
backend/.venv/bin/python scripts/dev/summarize_local_auth_audit.py \
  --report /tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-report.json \
  --output /tmp/academy-manager-local/evidence/20260628-production-scale-audit/audit-summary.md
```

Each failed Playwright test becomes a `BUG-CANDIDATE-*` section with error text
and attachment paths. Promote candidates to confirmed bugs below only after
reproducing the user-facing failure and filling in the required template.

## Required Bug Entry Template

### BUG-000: Short Title

Bug ID: BUG-000

Status: new | reproduced | fixing | fixed | verified | deferred

Severity: P0 | P1 | P2 | P3

Persona: admin | coach | parent | public | shared

Role: concrete role or membership used

Route: route under test

Workflow: user-facing workflow under test

Seeded Account: local test account email or generated synthetic account id

Environment:

- Frontend URL:
- Backend URL:
- Browser/project:
- Viewport:
- Dataset:
- Command:

Reproduction Steps:

1. Step one.
2. Step two.
3. Step three.

Expected Result:

- What the real user should see or be able to do.

Actual Result:

- What the user actually sees, including visible copy, stuck state, wrong
  redirect, wrong data, or failed control.

Evidence:

- Screenshot:
- Trace:
- Video:
- Backend Log Excerpt:
- Frontend Console:
- Network/API Evidence:

Root Cause:

- File/function/component/API where the bad value or behavior originates.
- How the data/control flow reaches the user-visible failure.

Shared Cause Review:

- Other routes/workflows likely affected by the same cause.
- Tenant/auth/billing/offline/data-scale dependency involved, if any.

Fix:

- Files changed.
- Behavior changed.
- Why this addresses the root cause rather than only the symptom.

Regression Test:

- Failing command/test added before fix.
- Passing command/test after fix.

Rerun Result:

- Real-user workflow rerun command.
- Evidence path for the rerun.
- Result: pass | fail | blocked.

## Active Bugs

### BUG-001: Local Dynamic Detail Fixtures Were Written To The Wrong Mongo

Bug ID: BUG-001

Status: verified

Severity: P1

Persona: admin

Role: seeded owner/admin

Route: `/admin/payouts/[payoutId]`, `/admin/registrations/[applicationId]`,
`/admin/waivers/[waiverId]`, `/admin/waivers/signatures/[signatureId]`

Workflow: Load seeded dynamic admin detail routes during full route inventory.

Seeded Account: `ramchand4685@gmail.com`

Environment:

- Frontend URL: `http://blno.localhost:3000`
- Backend URL: `http://127.0.0.1:8001`
- Browser/project: `local-auth-chromium-mobile`
- Viewport: Playwright mobile project
- Dataset: local BLNO SaaS staging plus synthetic scale fixtures
- Command: `pnpm exec playwright test -c playwright.local-auth.config.ts`

Reproduction Steps:

1. Start the Docker SaaS staging stack with Mongo exposed on host port `27018`.
2. Run host-side scale/env/readiness helpers that default to Mongo port `27017`.
3. Run the local-auth dynamic route inventory against admin detail routes.

Expected Result:

- Seeded payout, registration, waiver, and waiver signature detail routes load
  without 404 API failures.

Actual Result:

- The Playwright report captured 404 API failures for all four dynamic admin
  detail routes because the fixtures were inserted into the wrong local Mongo.

Evidence:

- Screenshot:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-artifacts/local-auth-inventory-local-4bc9d-ith-seeded-id-substitutions-local-auth-chromium-mobile/test-failed-1.png`
- Screenshot:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-artifacts/local-auth-inventory-local-6be02-ith-seeded-id-substitutions-local-auth-chromium-mobile/test-failed-1.png`
- Screenshot:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-artifacts/local-auth-inventory-local-bbb01-ith-seeded-id-substitutions-local-auth-chromium-mobile/test-failed-1.png`
- Screenshot:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-artifacts/local-auth-inventory-local-0b977-ith-seeded-id-substitutions-local-auth-chromium-mobile/test-failed-1.png`
- Network/API Evidence:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/audit-summary-latest.md`
  `BUG-CANDIDATE-001` through `BUG-CANDIDATE-004`

Root Cause:

- `scripts/dev/saas_staging.sh` host helpers hardcoded or inherited
  `mongodb://127.0.0.1:27017`, while Docker Compose exposed staging Mongo on
  `127.0.0.1:27018`.

Shared Cause Review:

- Any host-side staging helper that reads or writes Mongo could produce false
  negatives or corrupt audit evidence if it targets a different local Mongo
  than the backend uses.

Fix:

- Added `compose_mongo_url()` to `scripts/dev/saas_staging.sh` and routed seed,
  scale, local-auth-env, readiness, gate, artifact, migration replay, and smoke
  helper calls through the Compose-exposed Mongo port.

Regression Test:

- `backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_saas_staging_scale_command.py -q`

Rerun Result:

- Full real-user inventory rerun passed: `LOCAL_AUTH_E2E=1 pnpm exec playwright
  test -c playwright.local-auth.config.ts` => 72 passed.
- Evidence summary:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/audit-summary-latest.md`

### BUG-002: Coach Passport Inventory Selected A Student With No Active Pathway Level

Bug ID: BUG-002

Status: verified

Severity: P2

Persona: coach

Role: seeded coach

Route: `/coach/students/[studentId]/passport`

Workflow: Coach opens a seeded student's skill passport from the route
inventory.

Seeded Account: `gowtham@blno.academy`

Environment:

- Frontend URL: `http://blno.localhost:3000`
- Backend URL: `http://127.0.0.1:8001`
- Browser/project: `local-auth-chromium-mobile`
- Viewport: Playwright mobile project
- Dataset: local BLNO SaaS staging plus synthetic scale fixtures
- Command: `pnpm exec playwright test -c playwright.local-auth.config.ts`

Reproduction Steps:

1. Export `LOCAL_AUTH_COACH_STUDENT_ID` from the local BLNO staging database.
2. Run the dynamic route inventory for `/coach/students/[studentId]/passport`.

Expected Result:

- The seeded coach student passport renders meaningful passport content.

Actual Result:

- The API returned a 404 because the selected student had no active
  `student_level_progress` row.

Evidence:

- Screenshot:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-artifacts/local-auth-inventory-local-acc2c-ith-seeded-id-substitutions-local-auth-chromium-mobile/test-failed-1.png`
- Network/API Evidence:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/audit-summary-latest.md`
  `BUG-CANDIDATE-005`

Root Cause:

- `scripts/dev/export_local_auth_inventory_env.py` selected the first enrolled
  coach student without verifying that the student had an active pathway level.
  The local staging database also had no `student_level_progress` rows.

Shared Cause Review:

- Coach passport, skill board, teaching focus, and progress workflows all depend
  on pathway placement data. Route inventory IDs must be selected from data that
  satisfies those workflow prerequisites.

Fix:

- The env exporter now selects a coach session only when it has a future
  occurrence and a student with active level progress. The scale seed now
  self-repairs local audit prerequisites by adding one future coach occurrence
  and one active level progress fixture from existing seeded program/level data.

Regression Test:

- `backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_local_auth_inventory_env_export.py backend/v2/tests/unit/test_blno_scale_seed.py -q`

Rerun Result:

- Full real-user inventory rerun passed: `LOCAL_AUTH_E2E=1 pnpm exec playwright
  test -c playwright.local-auth.config.ts` => 72 passed.
- Evidence summary:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/audit-summary-latest.md`

### BUG-003: Parent Billing Portal Exposed Raw Stripe Missing-Customer Error

Bug ID: BUG-003

Status: verified

Severity: P2

Persona: parent

Role: seeded parent

Route: `/parent/payments`

Workflow: Parent clicks `Billing portal`.

Seeded Account: `manojedward.btech@gmail.com`

Environment:

- Frontend URL: `http://blno.localhost:3000`
- Backend URL: `http://127.0.0.1:8001`
- Browser/project: `local-auth-chromium-mobile`
- Viewport: Playwright mobile project
- Dataset: local BLNO SaaS staging
- Command: `pnpm exec playwright test -c playwright.local-auth.config.ts`

Reproduction Steps:

1. Sign in as the seeded parent.
2. Open `/parent/payments`.
3. Click `Billing portal`.

Expected Result:

- Parent sees the prerequisite message: `Start autopay for an enrollment first`.

Actual Result:

- Parent saw a raw provider error including `No such customer:
  'cus_blno_test_0001'`.

Evidence:

- Screenshot:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-artifacts/local-auth-qa-local-authen-56590-ct-and-wrong-role-redirects-local-auth-chromium-mobile/test-failed-1.png`
- Frontend Console/API Evidence:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/audit-summary-latest.md`
  `BUG-CANDIDATE-006`

Root Cause:

- `frontend/app/(parent)/parent/payments/page.tsx` only normalized some billing
  prerequisite errors and allowed stale Stripe customer errors to surface as raw
  provider copy.

Shared Cause Review:

- Billing recovery and portal entry points should normalize stale provider
  objects into user-actionable prerequisite states, while preserving details in
  logs/server diagnostics.

Fix:

- Parent payments UI now maps `No such customer` detail text to the same billing
  portal prerequisite message.

Regression Test:

- `node --test frontend/lib/parent-billing-recovery-ui.node-test.mjs`

Rerun Result:

- Focused authenticated QA rerun passed: `LOCAL_AUTH_E2E=1 pnpm exec playwright
  test -c playwright.local-auth.config.ts e2e/specs/local-auth-qa.spec.ts` =>
  7 passed.
- Full real-user inventory rerun passed: `LOCAL_AUTH_E2E=1 pnpm exec playwright
  test -c playwright.local-auth.config.ts` => 72 passed.

### BUG-004: Coach QA Defect Coverage Used Stale Schedule And Dashboard Selectors

Bug ID: BUG-004

Status: verified

Severity: P3

Persona: coach

Role: seeded coach

Route: `/coach/sessions`, `/coach/dashboard`

Workflow: QA defect coverage checks coach schedule navigation and blocker route
rendering.

Seeded Account: `gowtham@blno.academy`

Environment:

- Frontend URL: `http://blno.localhost:3000`
- Backend URL: `http://127.0.0.1:8001`
- Browser/project: `local-auth-chromium-mobile`
- Viewport: Playwright mobile project
- Dataset: local BLNO SaaS staging
- Command: `pnpm exec playwright test -c playwright.local-auth.config.ts`

Reproduction Steps:

1. Run `local-auth-qa.spec.ts` against the seeded coach account.
2. Observe the schedule test expecting hardcoded `6:00 PM`.
3. Observe the dashboard test expecting `coach-dashboard`.

Expected Result:

- QA follows seeded dynamic occurrence data and asserts the current coach
  dashboard surface.

Actual Result:

- QA failed on stale test assumptions: hardcoded `6:00 PM` and old
  `coach-dashboard` selector.

Evidence:

- Screenshot:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-artifacts/local-auth-qa-local-authen-05346-oming-session-from-schedule-local-auth-chromium-mobile/test-failed-1.png`
- Screenshot:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/playwright-artifacts/local-auth-qa-local-authen-0c2ab-ead-of-stale-loading-states-local-auth-chromium-mobile/test-failed-1.png`
- Network/API Evidence:
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/audit-summary-latest.md`
  `BUG-CANDIDATE-007` and `BUG-CANDIDATE-008`

Root Cause:

- `frontend/e2e/specs/local-auth-qa.spec.ts` encoded stale UI assumptions
  instead of using exported local-auth dynamic IDs and the current
  `coach-day-hub` dashboard surface.

Shared Cause Review:

- Real-user defect coverage should follow seeded data contracts and stable
  current UI test IDs, not presentation strings that age out with the calendar.

Fix:

- The schedule test now follows `LOCAL_AUTH_COACH_OCCURRENCE_ID`, and dashboard
  coverage now asserts `coach-day-hub` / `Coach Day Hub`.

Regression Test:

- Static coverage is included in the local-auth spec checks. Full Playwright
  rerun remains required for final verification.

Rerun Result:

- Focused authenticated QA rerun passed: `LOCAL_AUTH_E2E=1 pnpm exec playwright
  test -c playwright.local-auth.config.ts e2e/specs/local-auth-qa.spec.ts` =>
  7 passed.
- Full real-user inventory rerun passed: `LOCAL_AUTH_E2E=1 pnpm exec playwright
  test -c playwright.local-auth.config.ts` => 72 passed.
