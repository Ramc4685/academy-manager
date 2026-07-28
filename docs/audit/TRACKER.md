# Audit Remediation Tracker

Source audit: [2026-07-20-production-readiness-audit.md](2026-07-20-production-readiness-audit.md)
Plans: one file per item under [plans/](plans/). Each plan is self-contained — usable as a PR description or GitHub issue body.

## How to use this tracker

1. Pick an item (respect the **Depends on** column). Read its plan file.
2. Create a branch/PR (or GitHub issue) named after the item ID, e.g. `fix/C1-mypy-gate`.
3. When the PR merges: update the **Status** and **PR/Issue** columns here, and flip the `Status:` line at the top of the plan file to `DONE (PR #NNN, YYYY-MM-DD)`.
4. If an item is rejected/obsoleted, mark it `WONT-FIX` with a one-line reason here — don't delete the plan.
5. Statuses: `TODO` · `IN PROGRESS` · `DONE` · `WONT-FIX` · `BLOCKED (by <id>)`.

> Agent instruction: any session that completes one of these items MUST update this file and the plan's Status line in the same PR.

## Critical (pre-conditions for scaling)

| ID | Item | Plan | Size | Depends on | Status | PR/Issue |
|---|---|---|---|---|---|---|
| C1 | Un-break the mypy gate (also quick-win #2) | [plans/C1-mypy-gate.md](plans/C1-mypy-gate.md) | M | — | DONE | #311 |
| C2 | Observability: error tracking + request correlation | [plans/C2-observability.md](plans/C2-observability.md) | M | — | DONE | #314 |
| C3 | Rate limiter: real client IP + webhook coverage | [plans/C3-rate-limiter.md](plans/C3-rate-limiter.md) | S | — | DONE | #312 |
| C4 | Kill boot-time academy_id closures (parent reads + coach writes) | [plans/C4-tenant-boot-closure.md](plans/C4-tenant-boot-closure.md) | M | — | DONE | [#317](https://github.com/Ramc4685/academy-manager/pull/317) |

## Quick wins

| ID | Item | Plan | Size | Depends on | Status | PR/Issue |
|---|---|---|---|---|---|---|
| QW1 | Re-point pnpm security overrides | [plans/QW1-pnpm-overrides.md](plans/QW1-pnpm-overrides.md) | XS | — | DONE | #310 |
| QW2 | (merged into C1) | — | — | C1 | DONE | #311 |
| QW3 | Scrub weak example credentials | [plans/QW3-env-example-creds.md](plans/QW3-env-example-creds.md) | XS | — | DONE | #310 |
| QW4 | Delete orphaned legacy bytecode dirs | [plans/QW4-orphaned-bytecode.md](plans/QW4-orphaned-bytecode.md) | XS | — | DONE | verified 2026-07-24: backend/routers, backend/services, backend/tests gone from origin/main |
| QW5 | Add CSP + HSTS headers | [plans/QW5-csp-hsts.md](plans/QW5-csp-hsts.md) | S | — | PARTIAL | #315 — HSTS live; CSP still Content-Security-Policy-Report-Only, not enforcing (see next.config.ts comment) |
| QW6 | Fix local pnpm typecheck (stale .next/types) | [plans/QW6-local-typecheck.md](plans/QW6-local-typecheck.md) | XS | — | DONE | #310 |
| QW7 | Widen CI coverage gate to v2 | [plans/QW7-coverage-gate.md](plans/QW7-coverage-gate.md) | XS | — | DONE | #310 |
| QW8 | Dedupe mapRoleToStatus | [plans/QW8-dedupe-maprole.md](plans/QW8-dedupe-maprole.md) | XS | — | DONE | #310 |
| QW9 | Move tracked repo-root clutter | [plans/QW9-root-clutter.md](plans/QW9-root-clutter.md) | XS | — | DONE | #310 |
| QW10 | Lease-lock scheduler jobs | [plans/QW10-scheduler-lease.md](plans/QW10-scheduler-lease.md) | S | — | DONE | |

## Medium-term

| ID | Item | Plan | Size | Depends on | Status | PR/Issue |
|---|---|---|---|---|---|---|
| MT1 | Drain the composition root (billing math → application layer) | [plans/MT1-drain-composition-root.md](plans/MT1-drain-composition-root.md) | L | — | TODO | |
| MT2 | Split runtime vs dev requirements | [plans/MT2-split-requirements.md](plans/MT2-split-requirements.md) | S | — | DONE | [#356](https://github.com/Ramc4685/academy-manager/pull/356) |
| MT3 | Real-auth e2e job in CI | [plans/MT3-real-auth-e2e.md](plans/MT3-real-auth-e2e.md) | M | — | DONE | [#361](https://github.com/Ramc4685/academy-manager/pull/361) |
| MT4 | Structural tenancy test | [plans/MT4-structural-tenancy-test.md](plans/MT4-structural-tenancy-test.md) | S | C4 (ideally after) | DONE | [#321](https://github.com/Ramc4685/academy-manager/pull/321) |
| MT5 | Split frontend monolith pages | [plans/MT5-split-monolith-pages.md](plans/MT5-split-monolith-pages.md) | L | DS3 (dialog primitives help) | DONE | #331 |

## UI — Combine screens

| ID | Item | Plan | Size | Depends on | Status | PR/Issue |
|---|---|---|---|---|---|---|
| UIC1 | Users directory: coaches+parents+users → role tabs | [plans/UIC1-users-directory.md](plans/UIC1-users-directory.md) | S | — | DONE | [#324](https://github.com/Ramc4685/academy-manager/pull/324) |
| UIC2 | Pause requests → 5th tab of Requests | [plans/UIC2-pause-into-requests.md](plans/UIC2-pause-into-requests.md) | S | — | DONE | #322 |
| UIC3 | Session economics + Dues → Reports tabs | [plans/UIC3-reports-consolidation.md](plans/UIC3-reports-consolidation.md) | M | — | TODO | |
| UIC4 | Coach payslip → Payouts tab | [plans/UIC4-payslip-into-payouts.md](plans/UIC4-payslip-into-payouts.md) | S | — | DONE | [#346](https://github.com/Ramc4685/academy-manager/pull/346) |
| UIC5 | Progress → tab of student/session detail | [plans/UIC5-progress-tabs.md](plans/UIC5-progress-tabs.md) | S | — | DONE | [#328](https://github.com/Ramc4685/academy-manager/pull/328) |
| UIC6 | Registrations + Waitlist + Level-up queue → Admissions | [plans/UIC6-admissions-queues.md](plans/UIC6-admissions-queues.md) | M | — | DONE | [#348](https://github.com/Ramc4685/academy-manager/pull/348) |
| UIC7 | Self-service policy → Settings section | [plans/UIC7-settings-selfservice.md](plans/UIC7-settings-selfservice.md) | XS | — | DONE | Moved into `/admin/settings?panel=self-service`; old URL redirects |
| UIC8 | Delete shared Calendar/Messages stubs | [plans/UIC8-delete-shared-stubs.md](plans/UIC8-delete-shared-stubs.md) | XS | UIM13 decision | DONE | [#327](https://github.com/Ramc4685/academy-manager/pull/327) |

## UI — Missing features

| ID | Item | Plan | Size | Depends on | Status | PR/Issue |
|---|---|---|---|---|---|---|
| UIM1 | Platform/tenant-admin persona UI | [plans/UIM1-platform-persona.md](plans/UIM1-platform-persona.md) | L | DS1-3 recommended | TODO | |
| UIM2 | GET /me/memberships + real TenantSwitcher | [plans/UIM2-memberships-route.md](plans/UIM2-memberships-route.md) | S | — | DONE | [#366](https://github.com/Ramc4685/academy-manager/pull/366) |
| UIM3 | Funnel/attendance/utilization reports UI | [plans/UIM3-analytics-reports.md](plans/UIM3-analytics-reports.md) | M | UIC3 (same surface) | DONE | [#362](https://github.com/Ramc4685/academy-manager/pull/362) |
| UIM4 | Session-type management UI | [plans/UIM4-session-types.md](plans/UIM4-session-types.md) | S | — | TODO | |
| UIM5 | Billing-enrollment move/override UI | [plans/UIM5-billing-enrollment-move.md](plans/UIM5-billing-enrollment-move.md) | M | — | TODO | |
| UIM6 | Bulk user invite UI | [plans/UIM6-bulk-invite.md](plans/UIM6-bulk-invite.md) | S | UIC1 (same surface) | TODO | |
| UIM7 | Coach skill-notes UI | [plans/UIM7-skill-notes.md](plans/UIM7-skill-notes.md) | S | — | DONE | [#353](https://github.com/Ramc4685/academy-manager/pull/353) |
| UIM8 | Tuition-discounts report UI | [plans/UIM8-tuition-discounts.md](plans/UIM8-tuition-discounts.md) | S | — | DONE | [#359](https://github.com/Ramc4685/academy-manager/pull/359) — built on `/admin/dues` since UIC3 hasn't merged yet |
| UIM9 | Platform-fallback billing visibility | [plans/UIM9-platform-fallback-setting.md](plans/UIM9-platform-fallback-setting.md) | S | — | DONE | [#352](https://github.com/Ramc4685/academy-manager/pull/352) |
| UIM10 | Curriculum authoring extras | [plans/UIM10-curriculum-extras.md](plans/UIM10-curriculum-extras.md) | S | — | DONE | [#354](https://github.com/Ramc4685/academy-manager/pull/354) |
| UIM11 | Franchise cross-academy rollup | [plans/UIM11-franchise-rollup.md](plans/UIM11-franchise-rollup.md) | L | UIM2, owner role | TODO | |
| UIM12 | Student login persona | [plans/UIM12-student-persona.md](plans/UIM12-student-persona.md) | L | — | DONE | [#371](https://github.com/Ramc4685/academy-manager/pull/371) — ships dark behind `enable_student_login`; no unlink/re-invite path yet (follow-up before enabling) |
| UIM13 | Real Messages inbox + Calendar | [plans/UIM13-messages-calendar.md](plans/UIM13-messages-calendar.md) | L | — | TODO | |

## UI — Design standardization (do in order)

| ID | Item | Plan | Size | Depends on | Status | PR/Issue |
|---|---|---|---|---|---|---|
| DS1 | Single-source color tokens + contrast fixes | [plans/DS1-tokens.md](plans/DS1-tokens.md) | S | — | DONE | #313 |
| DS2 | De-hex design-system components | [plans/DS2-dehex-ds.md](plans/DS2-dehex-ds.md) | S | DS1 | DONE | #316 |
| DS3 | Add missing DS primitives (FormField, Skeleton, EmptyState, Modal, Toast) | [plans/DS3-primitives.md](plans/DS3-primitives.md) | M | DS2 | DONE | #323 — verified 2026-07-24: form-field.tsx, skeleton.tsx, empty-state.tsx, modal.tsx, toast.tsx all on origin/main |
| DS4 | Migrate parent surface onto DS | [plans/DS4-parent-migration.md](plans/DS4-parent-migration.md) | L | DS1-3 | DONE | waivers/dashboard/children/requests #330; progress/payments [#350](https://github.com/Ramc4685/academy-manager/pull/350) |
| DS5 | Desktop Chromium Playwright project | [plans/DS5-desktop-e2e.md](plans/DS5-desktop-e2e.md) | S | — | DONE | [#364](https://github.com/Ramc4685/academy-manager/pull/364) |
| DS6 | Polish: server-side gating, nav restructure, dead offline code, manifest colors | [plans/DS6-polish.md](plans/DS6-polish.md) | M | UIC merges help | TODO | |

## Suggested first wave

QW1 → QW3 → QW4 → QW6 → QW7 → QW8 → QW9 (one afternoon, all independent), then C1, C3, DS1 in parallel.

## Corrections found while writing plans (2026-07-20)

Plan-writing agents re-verified every citation; four audit claims needed adjustment (details in each plan):

- **QW1**: the pnpm overrides already work — they exist in `pnpm-workspace.yaml`; the task shrinks to deleting the ignored duplicate `"pnpm"` key in `package.json`.
- **QW4**: `backend/routers/`, `backend/services/`, `backend/tests/` are already gone from git; only local `__pycache__`/`uv.lock` cleanup remains.
- **MT4**: the structural tenancy test already exists (`backend/v2/tests/test_no_raw_tenant_mongo_access.py`) but blanket-exempts `contexts/*/infrastructure` and composition — task is "tighten", not "create". It also mislists `users`/`academies`/`academy_memberships` as tenant-owned.
- **DS6(d)**: `frontend/lib/offline/*` is NOT dead — imported by `app/(coach)/layout.tsx:10` and `coach/needs-review/page.tsx:5-6`, guarded by `coach-offline-writes.spec.ts`. Sub-item re-scoped to WONT-FIX.
- **UIC5**: student detail already has 5 tabs (not 2); plan uses tab-as-link subroutes so the monolith shrinks rather than grows.
- Also noted: `composition/admin.py` has grown to 7,203 lines (was 6,679 at audit time); messages are already persisted per-recipient (`MongoMessageRepository.for_recipient`), which shrinks UIM13 Phase 1 to thin read routes.
