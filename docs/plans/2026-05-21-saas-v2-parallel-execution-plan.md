# SaaS v2 Parallel Execution Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert academy-manager into a clean v2-only SaaS foundation where each academy is a tenant, without migrating legacy data or supporting legacy SaaS routes.

**Architecture:** SaaS mode is v2-only. Tenant access is resolved explicitly by domain/subdomain, validated through `academy_memberships`, and enforced through request-scoped tenant context plus `TenantScopedRepository`. Work is split into independent streams where possible, but core tenant/auth/schema decisions must land before downstream domain work.

**Tech Stack:** FastAPI, MongoDB/Motor, Firebase Auth, Stripe, Next.js 15, React 19, Tailwind, pytest, Playwright.

---

## How To Use This Plan With Multiple AI Coders

Use multiple AI coding sessions, but do not let them all edit the same files at the same time.

Recommended structure:

- One **orchestrator** agent owns sequencing, branch hygiene, reviews, and integration.
- Multiple **worker** agents own bounded streams with disjoint file ownership.
- One **reviewer/test** agent runs verification and looks for tenant leaks.

Use subagents when the work can be bounded to one subsystem and one output. Do not use subagents for cross-cutting architecture decisions unless they are doing read-only research.

Best approach:

1. Create one parent feature branch.
2. Create separate worktrees or branches per stream.
3. Merge streams only after their focused tests pass.
4. Run full backend tests after each integration.
5. Keep every PR/commit small enough to review.

## Critical Path

These tasks must be mostly sequential:

```text
ADR-0007
  -> SaaS config / route enforcement
  -> identity memberships + tenant resolution
  -> tenant bootstrap
  -> domain streams can begin safely
```

Do not start billing, attendance, coach payout, waiver, messaging, or reporting implementation until the membership and tenant-resolution contracts are stable.

## Recommended Workstreams

| Stream | Can run parallel? | Depends on | Primary owner |
| --- | --- | --- | --- |
| A. ADR and contracts | Starts first | None | Architect/orchestrator |
| B. SaaS route enforcement | Parallel after ADR draft | A | Backend worker |
| C. Identity memberships | Starts first after ADR | A | Backend worker |
| D. Tenant resolution middleware | Mostly with C | A, C contracts | Backend worker |
| E. Tenant bootstrap | After C/D interfaces stable | C, D | Backend worker |
| F. Tenant isolation tests/static checks | Parallel after B/C/D | B, C, D | Test worker |
| G. Session occurrences/attendance | After C/D stable | C, D | Backend worker |
| H. Enrollment events | Parallel with G | C, D | Backend worker |
| I. Billing ledger/idempotency | After C/D; can start design earlier | C, D | Backend worker |
| J. Coach payout | After G and I | G, I | Backend worker |
| K. Waivers/artifacts | Parallel after C/D | C, D | Backend worker |
| L. Messaging campaigns/deliveries | Parallel after C/D | C, D | Backend worker |
| M. Reporting read models | Last | G, H, I, J, K, L | Backend/frontend worker |
| N. Frontend tenant/admin UX | After API contracts | B through L | Frontend worker |

## Phase 0: Architecture Contract And Guardrails

### Task 0.1: Write ADR-0007

**Files:**

- Create: `docs/adr/0007-saas-tenant-model-and-membership-auth.md`
- Read: `docs/adr/0006-tenant-ready-single-tenant-shipped.md`
- Read: `docs/requirements/2026-05-21-saas-data-model-architecture-assessment.md`
- Read: `docs/data-ownership.md`

**Agent:** Architect/orchestrator.

**Acceptance criteria:**

- ADR states SaaS is v2-only.
- ADR rejects database-per-tenant for now.
- ADR defines global `users`, `academy_memberships`, and `platform_roles`.
- ADR defines tenant resolution order: subdomain, custom domain, approved internal header.
- ADR states no `default_academy_id` in SaaS request paths.
- ADR states legacy `/api/*` routes are forbidden in SaaS mode.

**Verification:**

```bash
rg -n "v2-only|academy_memberships|default_academy_id|legacy" docs/adr/0007-saas-tenant-model-and-membership-auth.md
```

### Task 0.2: Add SaaS Mode Config

**Files:**

- Modify: `backend/v2/shared/config/settings.py`
- Test: `backend/v2/tests/unit/test_settings.py` or create nearest equivalent.

**Agent:** Backend worker.

**Implementation shape:**

- Add `saas_mode: bool`.
- Add `allowed_internal_tenant_header: str | None` only if needed for internal jobs.
- Keep `default_academy_id` only for non-SaaS/local compatibility.
- In SaaS mode, code paths must reject fallback tenant behavior.

**Acceptance criteria:**

- SaaS mode can be enabled by env.
- `default_academy_id` is not treated as a valid tenant source in SaaS mode.
- Tests cover both SaaS and non-SaaS config behavior.

### Task 0.3: Enforce v2-Only SaaS Routing

**Files:**

- Inspect: `backend/server.py`
- Inspect: `backend/v2/main.py`
- Inspect: `backend/routers/*.py`
- Create or modify: route middleware/gateway mounting code near app composition.
- Test: `backend/tests` or `backend/v2/tests/interface`.

**Agent:** Backend worker.

**Acceptance criteria:**

- In SaaS mode, `/api/v2/*` remains available.
- In SaaS mode, legacy `/api/*` routes are rejected.
- Rejection is deterministic, ideally `410 Gone` or `404` with no legacy handler execution.
- Tests prove no SaaS request reaches legacy routers.

**Parallel note:** This can run while identity modeling starts, as long as it does not touch identity repository files.

## Phase 1: Membership-Based Identity And Tenant Resolution

### Task 1.1: Add Identity Domain Models

**Files:**

- Modify: `backend/v2/contexts/identity/domain/models.py`
- Modify: `backend/v2/shared/auth/claims.py`
- Test: `backend/v2/tests/unit/test_identity_domain.py`

**Agent:** Backend identity worker.

**Model targets:**

```text
User
- user_id
- firebase_uid
- email
- normalized_email
- display_name
- phone
- global_status

AcademyMembership
- membership_id
- academy_id
- user_id
- roles
- status

PlatformRole
- platform_role_id
- user_id
- role
- status
```

**Acceptance criteria:**

- `User` no longer treats `academy_id` as the source of tenancy for SaaS.
- `AuthClaims` can carry `academy_id`, `membership_id`, academy roles, and platform roles.
- Role checks are academy-specific.

### Task 1.2: Add Mongo Repositories And Indexes

**Files:**

- Create: `backend/v2/contexts/identity/infrastructure/mongo_membership_repo.py`
- Modify: `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py`
- Create migration under: `backend/v2/migrations/`
- Test: `backend/v2/tests/contract/test_identity_membership_repo.py`

**Agent:** Backend identity worker.

**Indexes:**

```text
users:
- unique(firebase_uid)
- unique(normalized_email)

academy_memberships:
- unique(academy_id, user_id)
- index(user_id, status)
- index(academy_id, roles, status)

platform_roles:
- unique(user_id, role)
```

**Acceptance criteria:**

- Membership repository supports lookup by `(academy_id, user_id)`.
- Membership repository supports listing academies for a user.
- Cross-tenant membership lookups do not leak.

### Task 1.3: Implement Tenant Resolution

**Files:**

- Create: `backend/v2/shared/tenancy/resolver.py`
- Modify: `backend/v2/shared/auth/middleware.py`
- Modify: `backend/v2/contexts/identity/application/use_cases/load_auth_claims.py`
- Test: `backend/v2/tests/application/test_load_auth_claims.py`
- Test: create `backend/v2/tests/interface/test_tenant_resolution.py`

**Agent:** Backend tenancy worker.

**Resolution order:**

1. Subdomain.
2. Custom domain.
3. Approved internal header for internal jobs/platform admin only.

**Acceptance criteria:**

- Tenant is never inferred from user alone.
- Missing membership rejects the request.
- Invalid domain rejects the request.
- Valid domain plus valid membership sets tenant context.
- `request.state.auth_claims` includes `membership_id`.

**Do not parallelize with:** major changes to `AuthClaims` unless contracts are already agreed.

### Task 1.4: Add Clean Tenant Bootstrap

**Files:**

- Create: `backend/v2/contexts/identity/application/use_cases/bootstrap_academy.py`
- Create: `backend/v2/interfaces/platform/bootstrap_routes.py` or equivalent platform/admin interface.
- Modify: `backend/v2/main.py` if route mounting is needed.
- Test: `backend/v2/tests/application/test_bootstrap_academy.py`
- Test: `backend/v2/tests/interface/test_platform_bootstrap.py`

**Agent:** Backend platform worker.

**Bootstrap creates:**

- Academy tenant.
- Owner user.
- Owner membership.
- Default academy settings.
- Default billing policy.
- Default waiver template.
- Default roles.
- Default feature flags.

**Acceptance criteria:**

- Bootstrap is idempotent.
- Bootstrap does not use legacy routes.
- Bootstrap does not use `default_academy_id` in SaaS mode.

## Phase 2: Tenant Isolation Verification

### Task 2.1: Tenant Isolation Test Harness

**Files:**

- Create: `backend/v2/tests/contract/test_saas_tenant_isolation.py`
- Add reusable fixtures under: `backend/v2/tests/contract/conftest.py`

**Agent:** Test worker.

**Required tests:**

- Cross-tenant read rejection.
- Cross-tenant write rejection.
- Missing tenant context rejection.
- Invalid membership rejection.
- Role-per-academy behavior.
- v2-only route enforcement.

**Acceptance criteria:**

- Every tenant-owned repository has at least one isolation test.
- Tests fail if a repository bypasses tenant context.

### Task 2.2: Static Raw Mongo Guard

**Files:**

- Create: `backend/v2/tests/test_no_raw_tenant_mongo_access.py`
- Optional: add import-linter config if already used.

**Agent:** Test worker.

**Acceptance criteria:**

- Raw Mongo access to tenant-owned collections is forbidden outside infrastructure/composition exceptions.
- Any exception is listed explicitly with rationale.

## Phase 3: Operational Domain Streams

These can run in parallel after Phase 1 contracts are stable.

### Stream G: Session Occurrences And Attendance

**Files:**

- Modify: `backend/v2/contexts/enrollment/domain/models.py`
- Create: `backend/v2/contexts/enrollment/infrastructure/mongo_occurrence_repo.py`
- Modify: `backend/v2/contexts/coaching/domain/models.py`
- Modify: `backend/v2/contexts/coaching/infrastructure/mongo_attendance_repo.py`
- Create migration under: `backend/v2/migrations/`
- Tests: `backend/v2/tests/unit/test_session_occurrence_domain.py`
- Tests: `backend/v2/tests/contract/test_attendance_occurrence_uniqueness.py`

**Agent:** Enrollment/coaching worker.

**Acceptance criteria:**

- `sessions` define recurring class.
- `session_occurrences` define actual dates.
- Attendance uniqueness is `(academy_id, occurrence_id, student_id)`.
- Weekly recurring classes can record attendance every week.

### Stream H: Enrollment Events

**Files:**

- Create: `backend/v2/contexts/enrollment/domain/events.py`
- Create: `backend/v2/contexts/enrollment/infrastructure/mongo_enrollment_event_repo.py`
- Modify enrollment use cases under: `backend/v2/contexts/enrollment/application/use_cases/`
- Tests: `backend/v2/tests/application/test_enrollment_events.py`

**Agent:** Enrollment worker.

**Acceptance criteria:**

- Pause, resume, move, withdrawal, waitlist, and promotion create events.
- Events include effective date, actor, reason, billing policy, billing result, credit/refund references.
- Enrollment current status is still queryable, but event log answers "what happened."

### Stream I: Billing Ledger And Idempotency

**Files:**

- Create or modify billing domain under: `backend/v2/contexts/billing/domain/`
- Create repositories under: `backend/v2/contexts/billing/infrastructure/`
- Create migration under: `backend/v2/migrations/`
- Tests: `backend/v2/tests/unit/test_billing_ledger.py`
- Tests: `backend/v2/tests/contract/test_billing_idempotency.py`

**Agent:** Billing worker.

**Models:**

- `invoices`
- `invoice_lines`
- `payments`
- `payment_allocations`
- `account_credit_ledger`

**Idempotency required for:**

- Invoice generation.
- Stripe webhook processing.
- Payment allocation.
- Overpayment credit creation.
- Refund recording.
- Reminder email generation.

**Acceptance criteria:**

- Invoice truth and payment truth are separate.
- Partial payment and overpayment are represented correctly.
- Every ledger write is safe to retry.

### Stream K: Waivers

**Files:**

- Modify: `backend/v2/contexts/onboarding/domain/models.py`
- Add repositories under: `backend/v2/contexts/onboarding/infrastructure/`
- Create migration under: `backend/v2/migrations/`
- Tests: `backend/v2/tests/application/test_waiver_signatures.py`

**Agent:** Onboarding/waiver worker.

**Acceptance criteria:**

- Waiver signatures are per student.
- Signature points to immutable waiver template version and artifact ID.
- Admin can know exactly what was signed.

### Stream L: Messaging

**Files:**

- Modify or promote: `backend/v2/shared/comms/messages.py`
- Consider new context if rules become complex: `backend/v2/contexts/communications/`
- Create migration under: `backend/v2/migrations/`
- Tests: `backend/v2/tests/application/test_message_campaigns.py`

**Agent:** Communications worker.

**Acceptance criteria:**

- Campaigns support academy, session, parent, coach, selected family, and payment-risk audiences.
- Deliveries record per-recipient state.
- Direct messages resolve recipients by search, not typed IDs.

## Phase 4: Finance And Reporting

### Stream J: Coach Payout

**Depends on:** Session occurrences and billing ledger.

**Files:**

- Create or promote Finance context: `backend/v2/contexts/finance/`
- Create repositories and migrations for payout periods, payouts, payout occurrences.
- Tests: `backend/v2/tests/unit/test_coach_payout_formula.py`
- Tests: `backend/v2/tests/application/test_coach_payout_period.py`

**Agent:** Finance worker.

**Acceptance criteria:**

- Assigned sessions do not create payout.
- Actual coached occurrences create payout.
- Substitute coaches are supported.
- Formula snapshot is stored for audit.

### Stream M: Reporting Read Models

**Depends on:** domain streams.

**Files:**

- Create reporting read models under: `backend/v2/contexts/reporting/` or `backend/v2/interfaces/admin/reports_routes.py`
- Frontend pages under: `frontend/app/(admin)/admin/reports/`
- Tests: backend reporting tests and frontend smoke tests.

**Agent:** Reporting/frontend worker.

**Acceptance criteria:**

- Reports are dashboard-first.
- Exports are secondary.
- Reports read from stable domain facts/read models, not scattered ad hoc queries.

## Phase 5: Frontend Work

Frontend should lag backend contracts by one stream. Do not let frontend define business truth.

**Files likely affected:**

- `frontend/app/(admin)/admin/**`
- `frontend/lib/api/**`
- `frontend/e2e/specs/**`

**Agent:** Frontend worker.

**Parallel-safe frontend slices:**

- Tenant/academy switcher shell.
- Admin settings cleanup.
- Students/users detail-edit screens.
- Sessions/occurrences admin UX.
- Billing ledger/invoices UX.
- Payout review UX.
- Waiver detail/signature UX.
- Message campaign composer UX.
- Dashboard reports UX.

**Acceptance criteria:**

- No legacy API calls in SaaS pages.
- No internal IDs shown in normal admin UI.
- Admin actions use v2 workflow endpoints.
- Playwright smoke passes for each page.

## Recommended Subagent Usage

Use subagents for:

- Read-only audits of code areas.
- Isolated backend streams with clear file ownership.
- Test harness creation.
- Frontend page implementation after API contracts are stable.
- Code review/security review after each stream.

Do not use subagents for:

- ADR final decisions.
- Shared auth claim contract changes without orchestration.
- Simultaneous edits to `AuthClaims`, middleware, and identity repositories by different workers.
- Billing ledger and payout formula in the same files at the same time.

Suggested subagent/team map:

| Agent | Role | Scope |
| --- | --- | --- |
| Orchestrator | Lead architect/integrator | ADR, sequencing, reviews, merges |
| Identity worker | Backend | `identity`, `auth`, memberships |
| Tenancy worker | Backend | tenant resolver, SaaS route enforcement |
| Test worker | QA/backend | isolation tests, static raw Mongo checks |
| Enrollment worker | Backend | occurrences, enrollment events |
| Billing worker | Backend | ledger, idempotency, Stripe |
| Finance worker | Backend | coach payout |
| Compliance worker | Backend | waivers, artifacts, audit |
| Comms worker | Backend | campaigns, deliveries |
| Frontend worker | Frontend | admin/parent/coach v2 UX |
| Reviewer | Code review/security | tenant leaks, auth bypass, money correctness |

## Integration Rules

- One worker owns one bounded context at a time.
- Workers must not change unrelated files.
- Every worker starts by reading:
  - `README.md`
  - `DEPLOYMENT.md`
  - `test_result.md`
  - relevant `docs/agent/*.md`
  - `docs/requirements/2026-05-21-saas-data-model-architecture-assessment.md`
  - this plan
- Every worker must state:
  - files changed
  - tests run
  - skipped checks
  - tenant isolation impact
- Orchestrator runs `git diff --check` before integration.
- Orchestrator runs focused tests after each stream.
- Full backend test suite runs after every phase.

## First Week Execution Order

Day 1:

1. Orchestrator writes ADR-0007.
2. Identity worker drafts membership domain/repository interfaces.
3. Tenancy worker audits route mounting and legacy route blocking options.
4. Test worker drafts tenant isolation test strategy.

Day 2:

1. Merge ADR-0007.
2. Implement SaaS config and route enforcement.
3. Implement identity membership models and migrations.
4. Add first membership repository tests.

Day 3:

1. Implement tenant resolution middleware.
2. Update auth claims to include membership.
3. Add domain/subdomain resolution tests.
4. Add invalid membership rejection tests.

Day 4:

1. Implement bootstrap use case.
2. Add v2-only enforcement tests.
3. Add static raw Mongo guard.
4. Start session occurrence design tests.

Day 5:

1. Stabilize Phase 0/1.
2. Run backend focused test suite.
3. Fix integration issues.
4. Prepare streams G/H/I/K/L as independent work packages.

## Three Coding Agent Prompt Pack

Use three coding agents in waves. Do not start all future-domain work immediately. The first wave establishes contracts; later waves use those contracts.

### Branch And Merge Setup

Recommended branches:

```bash
git checkout -b feat/saas-v2-foundation
git worktree add ../academy-manager-agent-a feat/saas-agent-a-identity
git worktree add ../academy-manager-agent-b feat/saas-agent-b-routing
git worktree add ../academy-manager-agent-c feat/saas-agent-c-tests
```

If your AI coding tool manages branches itself, still use this ownership model:

- Agent A owns identity/auth contract files.
- Agent B owns SaaS config, route enforcement, and bootstrap files.
- Agent C owns tests, guardrails, and static checks.

Merge order for Wave 1:

```text
1. Agent A ADR + identity contract
2. Agent B config/routing
3. Agent C tests/guards
```

Before every merge:

```bash
git status --short --branch
git diff --check
```

After every merge:

```bash
cd backend
source .venv/bin/activate
pytest backend/v2/tests/unit backend/v2/tests/application backend/v2/tests/interface -q
```

If the backend test command shape differs locally, use the nearest focused v2 pytest command and record it in `test_result.md`.

### Wave 1: Foundation Contracts

Run these three agents in parallel. Agent A owns shared identity contracts; Agents B and C must not edit `AuthClaims`, identity domain models, or identity repositories in Wave 1.

#### Agent A Prompt: Identity And ADR

```text
You are Agent A for the academy-manager SaaS v2 foundation.

Read first:
- AGENTS.md
- README.md
- DEPLOYMENT.md
- test_result.md
- docs/agent/architecture-rules.md
- docs/agent/backend-api-rules.md
- docs/agent/testing-verification.md
- docs/requirements/2026-05-21-saas-data-model-architecture-assessment.md
- docs/plans/2026-05-21-saas-v2-parallel-execution-plan.md

Mission:
Create the SaaS identity contract and ADR-0007. SaaS is v2-only. Legacy /api/* routes are not part of SaaS mode. Do not migrate old data.

Owned files:
- docs/adr/0007-saas-tenant-model-and-membership-auth.md
- backend/v2/contexts/identity/domain/models.py
- backend/v2/shared/auth/claims.py
- backend/v2/tests/unit/test_identity_domain.py

Do not edit:
- backend/server.py
- backend/v2/main.py
- backend/v2/shared/config/settings.py
- backend/v2/shared/auth/middleware.py
- backend/v2/shared/tenancy/*
- frontend/*

Implementation:
1. Write ADR-0007 with decisions:
   - SaaS v2-only
   - shared Mongo with academy_id
   - users are global identity
   - academy_memberships hold per-academy roles
   - platform_roles are separate
   - tenant resolution order is subdomain, custom domain, approved internal header
   - no default_academy_id in SaaS request paths
   - legacy routes forbidden in SaaS mode
2. Update identity domain models to support User, AcademyMembership, PlatformRole.
3. Update AuthClaims to include membership_id, academy roles, and platform roles while preserving existing tests as much as practical.
4. Add focused unit tests for role-per-academy semantics and immutable claims.

Testing:
- Run: cd backend && source .venv/bin/activate && pytest v2/tests/unit/test_identity_domain.py -q
- Run any existing auth claim tests that fail from your changes.
- Run git diff --check.

Output:
- Files changed.
- Tests run and results.
- Any compatibility concern for downstream tenant resolver.
- Do not mark complete if tests are failing unless you clearly document the blocker.
```

#### Agent B Prompt: SaaS Config And v2-Only Routing

```text
You are Agent B for the academy-manager SaaS v2 foundation.

Read first:
- AGENTS.md
- README.md
- DEPLOYMENT.md
- test_result.md
- docs/agent/backend-api-rules.md
- docs/agent/testing-verification.md
- docs/requirements/2026-05-21-saas-data-model-architecture-assessment.md
- docs/plans/2026-05-21-saas-v2-parallel-execution-plan.md

Mission:
Add SaaS mode configuration and block legacy /api/* routes in SaaS mode. SaaS traffic must be v2-only.

Owned files:
- backend/v2/shared/config/settings.py
- backend/server.py or backend app composition file that mounts legacy/v2 routes
- backend/v2/main.py only if needed for v2 mount behavior
- backend/v2/tests/unit/test_settings.py or nearest equivalent
- backend/v2/tests/interface/test_saas_route_enforcement.py

Do not edit:
- backend/v2/shared/auth/claims.py
- backend/v2/contexts/identity/domain/models.py
- backend/v2/contexts/identity/infrastructure/*
- backend/v2/shared/auth/middleware.py unless absolutely necessary
- frontend/*

Implementation:
1. Add a v2 settings flag for SaaS mode, e.g. V2_SAAS_MODE.
2. Keep default_academy_id only for non-SaaS/local compatibility.
3. In SaaS mode, reject legacy /api/* routes deterministically before they reach legacy routers.
4. Ensure /api/v2/* remains available.
5. Add tests proving:
   - SaaS mode blocks legacy /api/*.
   - SaaS mode allows /api/v2/*.
   - non-SaaS mode preserves existing behavior.
   - no legacy handler executes for SaaS requests.

Testing:
- Run focused settings tests.
- Run focused route enforcement tests.
- Run git diff --check.

Output:
- Files changed.
- Tests run and results.
- Exact status code chosen for blocked legacy routes.
- Any route mounting assumptions discovered.
```

#### Agent C Prompt: Tenant Test Harness And Guardrails

```text
You are Agent C for the academy-manager SaaS v2 foundation.

Read first:
- AGENTS.md
- README.md
- DEPLOYMENT.md
- test_result.md
- docs/agent/testing-verification.md
- docs/agent/backend-api-rules.md
- docs/requirements/2026-05-21-saas-data-model-architecture-assessment.md
- docs/plans/2026-05-21-saas-v2-parallel-execution-plan.md

Mission:
Create the SaaS guardrail test harness. Focus on tests and static checks. Do not implement identity or route behavior unless needed for tiny fixtures.

Owned files:
- backend/v2/tests/contract/test_saas_tenant_isolation.py
- backend/v2/tests/test_no_raw_tenant_mongo_access.py
- backend/v2/tests/contract/conftest.py if needed for reusable fixtures
- test_result.md

Do not edit:
- backend/v2/shared/auth/claims.py
- backend/v2/shared/auth/middleware.py
- backend/v2/contexts/identity/domain/models.py
- backend/v2/contexts/identity/infrastructure/*
- backend/server.py
- frontend/*

Implementation:
1. Add reusable test helpers for tenant_scope isolation.
2. Add tests for:
   - missing tenant context rejection
   - cross-tenant read rejection for existing TenantScopedRepository examples
   - cross-tenant write/update/delete rejection where practical
3. Add static test that flags raw Mongo access to tenant-owned collections outside approved directories.
4. Approved directories initially include infrastructure and explicitly documented composition exceptions only.
5. Update test_result.md with new guardrails and any tests that are expected to fail until Agent A/B land.

Testing:
- Run: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_saas_tenant_isolation.py -q
- Run static guard test.
- Run git diff --check.

Output:
- Files changed.
- Tests run and results.
- List of raw Mongo exceptions found.
- Which tests are expected to fail until Agent A or B merges.
```

### Wave 2: Tenant Resolution And Bootstrap

Start Wave 2 only after Wave 1 merges and focused tests pass.

#### Agent A Wave 2 Prompt: Membership Repositories

```text
Continue as Agent A.

Mission:
Implement Mongo repositories and migrations for academy_memberships and platform_roles.

Owned files:
- backend/v2/contexts/identity/infrastructure/mongo_membership_repo.py
- backend/v2/contexts/identity/infrastructure/mongo_user_repo.py
- backend/v2/migrations/<next>_identity_membership_indexes.py
- backend/v2/tests/contract/test_identity_membership_repo.py

Do not edit route enforcement, bootstrap, or frontend files.

Tests:
- pytest v2/tests/contract/test_identity_membership_repo.py -q
- pytest v2/tests/unit/test_identity_domain.py -q
```

#### Agent B Wave 2 Prompt: Tenant Resolver And Middleware

```text
Continue as Agent B.

Mission:
Implement explicit tenant resolution and membership validation.

Owned files:
- backend/v2/shared/tenancy/resolver.py
- backend/v2/shared/auth/middleware.py
- backend/v2/contexts/identity/application/use_cases/load_auth_claims.py only if needed and coordinated with Agent A
- backend/v2/tests/interface/test_tenant_resolution.py
- backend/v2/tests/application/test_load_auth_claims.py

Rules:
- Tenant resolution order: subdomain, custom domain, approved internal header.
- Never infer tenant from user alone.
- Reject if membership is missing.
- No default_academy_id in SaaS request paths.

Tests:
- pytest v2/tests/interface/test_tenant_resolution.py -q
- pytest v2/tests/application/test_load_auth_claims.py -q
```

#### Agent C Wave 2 Prompt: Bootstrap And Full Guardrail Tests

```text
Continue as Agent C.

Mission:
Implement clean SaaS bootstrap and expand guardrail tests.

Owned files:
- backend/v2/contexts/identity/application/use_cases/bootstrap_academy.py
- backend/v2/interfaces/platform/bootstrap_routes.py or agreed platform route location
- backend/v2/tests/application/test_bootstrap_academy.py
- backend/v2/tests/interface/test_platform_bootstrap.py
- test_result.md

Bootstrap creates:
- academy tenant
- owner user
- owner academy_membership
- default academy settings
- default billing policy
- default waiver template
- default roles
- default feature flags

Tests:
- pytest v2/tests/application/test_bootstrap_academy.py -q
- pytest v2/tests/interface/test_platform_bootstrap.py -q
- pytest v2/tests/contract/test_saas_tenant_isolation.py -q
```

### Wave 3: Parallel Domain Build

Start only after tenant resolution and bootstrap are stable.

Use these three assignments:

```text
Agent A: Session occurrences + attendance
Owns enrollment/coaching occurrence and attendance files.
Must change attendance uniqueness to academy_id + occurrence_id + student_id.

Agent B: Enrollment lifecycle events
Owns enrollment event domain/repository/use cases.
Must record pause/resume/move/withdraw/waitlist/promote events.

Agent C: Billing ledger + idempotency
Owns billing invoice/payment allocation/credit ledger files.
Must separate invoice truth from payment truth and make ledger writes retry-safe.
```

Do not start coach payout until Agent A and Agent C Wave 3 work are merged.

### Wave 4: Parallel Product Services

After Wave 3:

```text
Agent A: Coach payout
Depends on session occurrences and billing ledger.

Agent B: Waivers/artifacts
Can run after tenant resolution.

Agent C: Messaging campaigns/deliveries
Can run after tenant resolution.
```

### Wave 5: Frontend And Reporting

After backend contracts stabilize:

```text
Agent A: Reporting read models
Agent B: Admin SaaS frontend workflows
Agent C: Playwright/e2e and regression verification
```

Frontend must not call legacy `/api/*` in SaaS workflows.

## Stop Conditions

Pause parallel implementation if any of these happen:

- Auth claims contract changes unexpectedly.
- Tenant context can be missing without rejection.
- A v2 SaaS request reaches legacy `/api/*`.
- A repository can read another academy's data.
- Billing write is not idempotent.
- Attendance still uses `(academy_id, session_id, student_id)` for recurring classes.

## Final Phase Gate

Do not onboard a second academy until all are true:

```text
1. V2-only route enforcement exists.
2. Membership auth is implemented.
3. Tenant resolution is explicit.
4. default_academy_id is removed from SaaS paths.
5. Session occurrences are durable.
6. Attendance is occurrence-based.
7. Enrollment events exist.
8. Billing ledger exists.
9. Coach payout is occurrence-based.
10. Tenant isolation tests pass.
11. Audit logging exists.
12. Billing idempotency exists.
```
