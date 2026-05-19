# Wave 1A — Coach Today (Online + Offline Read)

**Goal:** Coach Today screen serves from v2 for 100% of coaches via edge route. Installable PWA. Cached reads work offline. **No offline writes in 1A** (those land in 1B after 1A is stable for one week).

**Prerequisite:** Phase 0 complete and merged.

**Exit gate (from plan §Wave 1A):**
1. Coach Today serves from v2 for 100% of coaches via edge route. Legacy coach pages untouched.
2. Lighthouse PWA ≥ 90, LCP < 2.5s on 4G simulated, install verified on real iOS Safari + Android Chrome.
3. Golden-master test: v2 Today response matches a hand-curated baseline for a seeded dataset.
4. No legacy regressions.

**Estimate:** ~2 weeks.

**Ticket ID convention:** `W1A-NN`. Estimates in ideal hours.

---

## Step 1 — Performance Baseline

### W1A-01 — Perf baseline (empty shell → auth → query → real data)
- **Type:** Frontend / Measurement
- **Depends on:** P0-17, P0-18
- **Estimate:** 4h
- **Description:** Per plan §0.10:
  1. Build empty coach shell (`app/(coach)/layout.tsx` + bottom tab nav, no data). Measure initial JS gz.
  2. Add Firebase Auth integration. Measure.
  3. Add TanStack Query + coach BFF client. Measure.
  4. (After W1A-12) Add Today screen with real data. Measure.
- **Acceptance:**
  - `docs/perf-baseline-coach.md` committed with four measurements + commit SHAs.
  - `size-limit` config for `(coach)/today` set to `baseline + 15%`.
  - `size-limit` gate flipped to **blocking** in `.github/workflows/v2-frontend.yml`.
  - Lighthouse CI gate for coach routes flipped to blocking (target ≥ 90 PWA, ≥ 90 perf).

---

## Step 2 — Backend: Identity Context (minimal)

### W1A-02 — `contexts/identity` aggregate + auth claim loading
- **Type:** Backend / Domain
- **Depends on:** P0-11, P0-12
- **Estimate:** 6h
- **Description:** Create `backend/v2/contexts/identity/`:
  - `domain/models.py`: `User`, `Role` (enum: admin/coach/parent), `AuthClaims` value object (`user_id`, `academy_id`, `roles`, `email`).
  - `application/use_cases/load_auth_claims.py`: given a verified Firebase token, hydrate `AuthClaims`. (Token verification stays in `shared/auth/firebase_verify.py`.)
  - `application/ports.py`: `UserRepository` protocol.
  - `infrastructure/mongo_user_repo.py` extending `TenantScopedRepository`.
  - FastAPI dependency `get_auth_claims()` in `shared/auth/` sets the tenancy `ContextVar`.
- **Acceptance:**
  - Unit tests on `AuthClaims` (immutability, role membership).
  - Use-case tests with port fake.
  - Integration test: a request with a valid Firebase token populates the tenancy context; a request with no token returns 401; wrong-tenant token returns 401.
  - Tenant-isolation test on `MongoUserRepo`.

---

## Step 3 — Backend: Enrollment Read Slice

### W1A-03 — `contexts/enrollment` read slice (Session + Roster)
- **Type:** Backend / Domain + Application
- **Depends on:** W1A-02
- **Estimate:** 8h
- **Description:** Create `backend/v2/contexts/enrollment/` — read-only slice only:
  - `domain/models.py`: `Session` aggregate (read-side fields: id, coach_id, start_at, end_at, location, capacity, status), `Enrollment` (id, session_id, student_id, status), `Student` (id, parent_id, full_name).
  - `application/use_cases/list_coach_sessions_for_date.py`: query sessions assigned to a coach on a date.
  - `application/use_cases/get_session_roster.py`: list enrollments + students for a session.
  - `application/ports.py`: `SessionQuery`, `EnrollmentQuery`, `StudentQuery`.
  - `infrastructure/`: mongo implementations extending `TenantScopedRepository`. **No writes in 1A.**
- **Acceptance:**
  - Pure-domain unit tests.
  - Use-case tests with port fakes.
  - Contract tests via testcontainers Mongo against seeded data.
  - Tenant-isolation test per repo.

### W1A-04 — Enrollment indexes migration
- **Type:** Backend / DB
- **Depends on:** W1A-03, P0-16
- **Estimate:** 1h
- **Description:** Migration script creating per plan §0.7:
  - `sessions`: `(academy_id, coach_id, start_at)`, `(academy_id, start_at)`.
  - `enrollments`: `(academy_id, session_id)`, `(academy_id, student_id)`.
  - `students`: `(academy_id, parent_id)`.
- **Acceptance:** Migration applied idempotently; queries from W1A-03 use the indexes (verified via `explain()` in a contract test).

---

## Step 4 — Backend: Coaching Write Slice

### W1A-05 — `contexts/coaching` Attendance aggregate + mark-attendance use case
- **Type:** Backend / Domain + Application
- **Depends on:** W1A-03, P0-14
- **Estimate:** 8h
- **Description:** Create `backend/v2/contexts/coaching/`:
  - `domain/models.py`: `Attendance` aggregate (`session_id`, `student_id`, `marked_by`, `marked_at`, `status: present|absent|late`).
  - `domain/events.py`: `Coaching.AttendanceMarked`.
  - `application/use_cases/mark_attendance.py`: validates session is in coach's assigned set for the date; rejects with `SessionNotAssigned` / `StudentNotEnrolled` / `SessionCancelled`. **Idempotent on `mutation_id`** via `@idempotent`. Writes outbox event in same transaction.
  - `application/ports.py`: `AttendanceRepository`.
  - `infrastructure/mongo_attendance_repo.py` extending `TenantScopedRepository`.
- **Acceptance:**
  - Domain unit tests on invariants.
  - Use-case tests covering all rejection paths.
  - Idempotency test: same `mutation_id` posted twice returns the same result, writes once.
  - Outbox row created in same transaction as attendance write (integration test).
  - Tenant-isolation test.

### W1A-06 — Attendance indexes migration
- **Type:** Backend / DB
- **Depends on:** W1A-05
- **Estimate:** 0.5h
- **Description:** Migration per plan §0.7:
  - `attendance`: `(academy_id, session_id, student_id)` **unique** (the idempotency invariant).
  - `attendance`: `(academy_id, coach_id, marked_at)`.
- **Acceptance:** Migration applied; unique constraint triggers `DuplicateKey` on test insert.

---

## Step 5 — Backend: Coach BFF

### W1A-07 — `interfaces/coach/today_routes.py` (`GET /api/v2/coach/today`)
- **Type:** Backend / Interface
- **Depends on:** W1A-03
- **Estimate:** 4h
- **Description:** Persona-shaped Today response composed from `list_coach_sessions_for_date` + `get_session_roster`:
  - Query params: `date=YYYY-MM-DD` (defaults to today in coach's TZ).
  - Response shape: `{ sessions: [{ id, start_at, end_at, location, roster: [{ student_id, full_name }] }] }`. **No payment, payout, or admin fields.**
  - Lightweight ETag for cache validation.
  - Negative test: parent or admin token gets 404 (not 403).
- **Acceptance:**
  - Route tests cover happy path, empty day, wrong-persona 404.
  - OpenAPI updated; `openapi-typescript` regen check passes.
  - p95 latency <300ms in load test (seeded dataset).

### W1A-08 — `interfaces/coach/attendance_routes.py` (`POST /api/v2/coach/attendance`)
- **Type:** Backend / Interface
- **Depends on:** W1A-05
- **Estimate:** 3h
- **Description:** Persona route calling `mark_attendance`:
  - Body: `{ session_id, student_id, status, mutation_id }`.
  - 200 on first mark; 200 on idempotent replay; 409 on conflict cases with structured error code (`SessionNotAssigned` / `StudentNotEnrolled` / `SessionCancelled` / `ConflictAttendanceExists`).
- **Acceptance:**
  - Route tests for happy path, idempotent replay, each rejection path, wrong-persona 404.

### W1A-09 — Coach BFF security tests (negative coverage from matrix)
- **Type:** Backend / Test
- **Depends on:** W1A-07, W1A-08, P0-07
- **Estimate:** 3h
- **Description:** For every row in the security matrix relevant to Wave 1A, write a negative test that asserts the right-persona route returns the data and the wrong-persona routes return 404.
- **Acceptance:** Matrix coverage table checked off in `docs/security-matrix.md`.

---

## Step 6 — Frontend: Coach Persona Shell

### W1A-10 — Coach route group layout + bottom nav
- **Type:** Frontend / UI
- **Depends on:** P0-17, P0-18
- **Estimate:** 5h
- **Description:** Create `frontend/app/(coach)/layout.tsx`:
  - Bottom tab navigation (Today / Sessions / Profile). 44pt minimum touch targets.
  - Top bar with academy name + offline indicator.
  - Route guard: redirects to `/login` if no auth; redirects to `/(parent)` or `/(admin)` if wrong role.
  - Loads no heavy libs (no calendar, no charts).
- **Acceptance:**
  - Renders within bundle budget for empty shell (set in W1A-01).
  - Lighthouse perf ≥ 90 on 4G simulated.

### W1A-11 — `lib/api/coach.ts` typed BFF client
- **Type:** Frontend / Infra
- **Depends on:** P0-19, W1A-07, W1A-08
- **Estimate:** 2h
- **Description:** Thin typed wrapper around generated `v2.d.ts` exposing `getToday(date)` and `markAttendance(payload)`. Uses base `lib/api/client.ts` (auth header, retry, dedup).
- **Acceptance:** Type-safe consumers; no `any`.

---

## Step 7 — Frontend: Today Screen

### W1A-12 — Coach Today page
- **Type:** Frontend / UI
- **Depends on:** W1A-10, W1A-11
- **Estimate:** 6h
- **Description:** `app/(coach)/today/page.tsx`:
  - TanStack Query `useQuery(['coach', 'today', date], …)`.
  - Stale-while-revalidate caching (5min stale, 1h max-age).
  - Date picker (today / +1 / -1; full picker in a deferred-loaded dialog).
  - List of sessions with start/end/location + roster count.
  - Tapping a session navigates to session detail.
  - Loading skeletons; empty state; error state with retry.
  - Zero raster images.
- **Acceptance:**
  - Renders within `coach/today` size budget.
  - LCP < 1.8s on simulated 4G (Lighthouse).
  - Playwright: today renders for seeded coach.

### W1A-13 — Coach session detail + mark attendance (online only)
- **Type:** Frontend / UI
- **Depends on:** W1A-12
- **Estimate:** 6h
- **Description:** `app/(coach)/sessions/[id]/page.tsx`:
  - Roster from `getToday` cache; refetched on focus.
  - Per-student toggle for present/absent/late.
  - On toggle: optimistic UI update + `markAttendance` POST with client-generated ULID `mutation_id`.
  - On 4xx (`SessionCancelled` / `StudentNotEnrolled` / `SessionNotAssigned`): roll back optimistic update, surface error toast.
  - **Offline behavior:** if `navigator.onLine === false`, the toggle is disabled and shows the offline indicator with text "You're offline — reconnect to mark attendance." **No queueing.**
- **Acceptance:**
  - Online happy path test (Playwright).
  - Online-loss-during-write test: simulate `offline` event mid-toggle → UI disables and shows the message, no error toast.
  - Rejection paths display a clear, persona-readable message.

---

## Step 8 — Frontend: Offline Reads + PWA

### W1A-14 — Serwist cache strategy for coach reads
- **Type:** Frontend / Infra
- **Depends on:** P0-18, W1A-11
- **Estimate:** 4h
- **Description:** Configure Serwist:
  - **Stale-while-revalidate** for `GET /api/v2/coach/today*` (cache, max 24h, 1 entry per date+coach).
  - **Network-only** for `POST /api/v2/coach/attendance` (no queueing in 1A).
  - **Cache-first** for static/icons/manifest.
  - TanStack Query persistence plugin (IndexedDB) scoped to `['coach', 'today', *]` keys only.
- **Acceptance:**
  - Manual test: load today online → toggle airplane mode → reload → roster still renders.
  - Manual test: airplane mode → tap toggle → offline indicator shown, no queueing.

### W1A-15 — PWA install prompts (login + onboarding moments)
- **Type:** Frontend / UI
- **Depends on:** P0-18, W1A-10
- **Estimate:** 4h
- **Description:** Use `useInstallPrompt()`:
  - Show install prompt on coach login success screen (Android Chrome).
  - Show iOS install instructions card (Safari detected, not standalone) on first login.
  - Persist dismissal for 30 days.
- **Acceptance:**
  - Real-device verification: install prompt fires on Android Chrome login; iOS instructions render on Safari.
  - Dismissed prompt does not re-appear for 30 days.

### W1A-16 — Offline indicator + service worker update flow
- **Type:** Frontend / UI
- **Depends on:** P0-18, W1A-10
- **Estimate:** 3h
- **Description:**
  - Reactive `useOnline()` hook driving the top-bar offline indicator.
  - SW update flow: new SW waits; toast "New version available — Refresh"; user click triggers `skipWaiting` + reload. No auto-update mid-session.
- **Acceptance:**
  - Toggling network in DevTools toggles the indicator.
  - Deploying a v+1 build to staging triggers the toast on a running v client; refresh loads new version.

---

## Step 9 — Verification

### W1A-17 — Playwright E2E suite (coach)
- **Type:** Test / E2E
- **Depends on:** W1A-12, W1A-13, W1A-14, W1A-15
- **Estimate:** 8h
- **Description:** Per plan §Verification, the coach E2E set for Wave 1A scope:
  - login → today renders
  - mark attendance (online happy path)
  - offline-read renders cached data
  - online-loss-during-write shows offline message, no queueing
  - install on Android (smoke via Playwright Chromium mobile)
  - iOS install instructions render (Playwright WebKit mobile)
  - service worker update toast appears + applies
  - logout
  - role-rejection (parent token → coach route → 404 / redirect)
- **Acceptance:** All 9 tests green in CI on every PR touching `(coach)/` or v2 coach routes.

### W1A-18 — Golden-master test for `GET /api/v2/coach/today`
- **Type:** Test / Contract
- **Depends on:** W1A-07
- **Estimate:** 3h
- **Description:** Seeded dataset fixture (`backend/v2/tests/fixtures/coach_today_seed.py`) + recorded baseline JSON. Test compares response against baseline modulo timestamps. Baseline updates require explicit `--update-baseline` flag and PR review.
- **Acceptance:** Test green; tampering with response shape fails CI; documented baseline update workflow.

### W1A-19 — Observability for Wave 1A
- **Type:** Ops
- **Depends on:** P0-15, W1A-07, W1A-12
- **Estimate:** 3h
- **Description:**
  - Web Vitals (LCP / CLS / INP) shipped from coach routes to PostHog via `web-vitals`.
  - OTel spans on `GET /api/v2/coach/today` and `POST /api/v2/coach/attendance`.
  - Grafana/PostHog dashboard: `coach.today` route latency p50/p95/p99, error rate, install events, install-prompt-shown vs install-accepted.
  - SLO: p95 read <300ms, p95 write <800ms.
- **Acceptance:** Dashboard renders with at least 1h of synthetic traffic. Alerts wired for SLO breach.

---

## Step 10 — Cutover

### W1A-20 — Canary cutover to 10% then 100%
- **Type:** Ops
- **Depends on:** W1A-17, W1A-18, W1A-19, P0-20
- **Estimate:** 4h elapsed (mostly waiting on canary soak)
- **Description:**
  1. Flip `ROUTE_COACH_TODAY=v2` for a 10% bucket of coach traffic at the edge.
  2. Soak 1h. Verify RED metrics within SLO, error rate ≤ legacy, install events normal.
  3. Flip to 100%.
  4. Soak 1 week before Wave 1B starts.
  5. Rollback: single env-var flip back to legacy.
- **Acceptance:**
  - 10% canary passes its 1h soak.
  - 100% holds 1 week with no SLO breach and no rollback.
  - Cutover runbook entry written in `docs/edge-routing.md`.

### W1A-21 — Legacy coach pages untouched verification
- **Type:** Test / Smoke
- **Depends on:** W1A-20
- **Estimate:** 1h
- **Description:** Legacy CRA coach pages remain reachable (admin can still hit the old paths via direct URL); legacy E2E suite still green; no service-worker installation on legacy origin.
- **Acceptance:** Legacy E2E green; manual smoke confirms.

---

## Wave 1A Exit Checklist

- [ ] W1A-01 baseline measured; size + Lighthouse gates blocking.
- [ ] W1A-02 … W1A-08 backend slices merged.
- [ ] W1A-09 security matrix coverage signed off.
- [ ] W1A-10 … W1A-16 frontend slices merged.
- [ ] W1A-17 E2E suite green.
- [ ] W1A-18 golden-master locked.
- [ ] W1A-19 observability dashboards live with alerts.
- [ ] W1A-20 100% traffic on v2 for 1 continuous week.
- [ ] W1A-21 legacy parity confirmed.
- [ ] Retro: capture pattern learnings before Wave 1B opens. Update ADRs if anything deviated.

**Do not start Wave 1B planning until this checklist is complete.**
