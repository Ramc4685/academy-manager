# Parent home, kid-first (slice 4) — implementation plan

> **For agentic workers:** this plan is executed by a Workflow (backend agent + frontend agent in parallel, then review, fix, verify). Each agent owns a disjoint file set. Do NOT `git commit` — the orchestrator commits between phases. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build-order item 4 of `docs/superpowers/specs/2026-09-04-role-model-and-screens-design.md`. The parent opens the app to ask *"How are my kids doing, and do I owe anything?"*. Home becomes **one card per child** — name, next session (day/time/venue), attendance this month (present/total), latest skill milestone — each card tapping into that child's Progress. Above the cards, a **balance banner only when** money is actually due or a payment failed. Everything else keeps its current order below. Tabs Home · Children · Payments · Progress already exist and do not change.

**Architecture:** The spec says *"Reorder only — no new data; the screens exist."* That is true of the **screens**, but not of the **reads**: the per-child "next session" lives only behind `GET /parent/children/{student_id}/schedule` (one call per child) and the latest skill milestone only behind `GET /parent/students/{student_id}/skill-updates` (again one per child). Rendering N children on Home would cost 2N round trips on a phone. So this slice adds **one aggregated parent BFF read, `GET /api/v2/parent/home`**, in `backend/v2/composition/parent.py` (2400 lines, far from the 4800 cap) that fans out server-side and returns a per-child card row plus a family-level balance summary. No new domain concepts, no new collections, **no migration**. The frontend replaces the single-child hero/metric stack with a card list driven by that one response, keeps the existing activity/requests/contact sections below, and deep-links each card to `/parent/progress?child=<student_id>` — a query param on an existing route, so **no new frontend route and no audit-manifest change**.

**Prior slices (pattern):** `docs/superpowers/plans/2026-09-05-owner-admin-split.md` (PR #660), `2026-09-06-assistant-coach.md` (PR #663), `2026-09-06-coach-phone-slice3.md` (PR #665).

## Decisions where the spec is silent (made 2026-09-06, do not re-litigate)

1. **One aggregated endpoint, not N client calls.** `GET /api/v2/parent/home` returns everything Home needs. The existing per-resource parent endpoints are untouched and keep their own consumers (`/parent/children`, `/parent/payments`, `/parent/progress` pages). Home stops issuing its current nine parallel queries and issues this one plus `GET /parent/academy` (needed for the timezone and the contact block).
2. **"Attendance this month" counts marked sessions, not scheduled ones.** `present` = attendance records for that child in the current calendar month with status `present`; `total` = all attendance records for that child in that month regardless of status. A session nobody marked is in neither number. The copy therefore reads "Attendance this month · 6 of 7" and, when `total == 0`, "No sessions marked yet this month" — never a fake 0%.
3. **The month boundary is the academy's timezone**, taken from `academy.timezone` (`get_academy_info`), not UTC and not the device. This mirrors the localisation rule from `project_541_followup_period_labels`: parent-facing period labels are academy-local.
4. **"Latest skill milestone" is the most recent of two things**: (a) the newest row from `list_progress_for_parent` for that child — that method already filters `progress_notes` to `visibility == "shared"` (PR #665) and blends in `session_feedback`, which is always parent-visible, so both kinds are legitimate milestones; and (b) the newest skill status change from `student_progress.get_recent_skill_updates`. Whichever has the later timestamp wins; the card shows a short label and the date. When neither exists the card says "No milestones yet".
5. **The balance banner is family-level, not per child.** Invoices are not reliably attributable to one child (`ParentInvoice.enrollment_id` is optional and legacy rows have none), so a per-child amount would be wrong. One banner above the cards.
6. **The banner shows when** `amount_due_cents > 0` (sum of `balance_due_cents` over invoices whose status is neither `void` nor `paid` — `InvoiceStatus` also has `partially_paid`, which counts as due, matching the `{"open","partially_paid"}` gate the pay endpoints already use) **or** a payment needs attention. Otherwise Home renders **no billing content at all** — that is the point of the slice.
6b. **"Payment failed" has two authoritative sources and we use both.** The real autopay-failure signal is per-enrollment: `list_enrollments_for_parent` already surfaces `last_attempt_outcome` / `last_failure_code` / `last_attempt_at` from `student_billing_enrollments`. The frontend additionally has a payments-history heuristic (`findPaymentNeedingAttention`). `payment_failed` is true when **either** any enrollment's `last_attempt_outcome` reads as a failure **or** the payments heuristic fires. Using only the payments heuristic would miss a failed autopay attempt that never produced a payment row.
7. **Cards tap into Progress, not a new child page.** `/parent/progress?child=<student_id>`. The Progress page's existing `SkillProgressSection` already has a child tab strip keyed by `student_id`; it learns to seed its selection from the query param. No `[studentId]` route is added, so the four backend audit tests and the two hard-coded route counts stay untouched.
8. **Child order is stable**: the order `list_children_for_parent` returns (which is the students query order), not sorted by next-session. Parents learn positions; re-ordering cards under them is worse than a slightly stale order.
9. **What leaves Home:** the single-child `ProgressHero` with its chip switcher, `MetricGrid`, `LatestNoteCard` and `NextClassCard` — all four are superseded by the per-child card. **What stays:** `RegistrationHero` (the zero-children case), `IssueStrip`, `PrimaryActionCard` **except** when its kind is `payment` (the banner owns money now), `RecentActivityCard`, `RequestsCard`, `AcademyContact` — in that order, below the cards.
10. **There is no announcements/messages preview on Home today** (messages live behind the header icon). The spec's "then the existing announcements/messages preview if present" is therefore satisfied by leaving `RecentActivityCard` where it is. Do not build a new preview in this slice.
11. **Degrade per child, not per page.** If one child's schedule or skill feed fails server-side, that card renders with the fields it has and the others are unaffected; the endpoint never 500s because one fan-out leg failed.
12. **`coach_name` on the next session is always `null` today.** `GetChildSchedule.execute` hardcodes it (`backend/v2/contexts/enrollment/application/use_cases/get_child_schedule.py:113`) even though the view model carries the field. The contract keeps the field for shape parity, the card renders the coach line only when it is non-null, and **this is not a bug to fix in this slice** — reviewers must not flag it. Do not attempt to populate it here.
13. **Attendance counts are counted, not paginated.** `list_attendance_for_parent` is paginated with a default limit of 50 and has no date filter, so folding it would silently undercount a busy family. The aggregator instead counts directly, mirroring the existing lifetime counters in `list_children_for_parent` (which already call `db["attendance"].count_documents` inside this same composition file) but with a `marked_at` range and an `academy_id` filter. Composition-level `db[...]` reads are the established pattern in this file; the raw-access ban applies to tenant-owned repositories, not here — always include `academy_id`.

## Global constraints

- Work only in `/Users/ramc/Documents/Code/academy-manager/.worktrees/parent-home` (branch `feat/parent-home-kid-first`). Backend venv is symlinked; frontend deps installed. Never touch the main checkout. Do not push.
- Do NOT run `git commit` / `git add` — the orchestrator commits. Leave the tree dirty.
- Backend commands from `backend/`: `.venv/bin/ruff format v2 && .venv/bin/ruff check v2 && .venv/bin/pytest v2/tests -n auto -q --tb=short`. Import-linter: `cd backend && PYTHONPATH=.. .venv/bin/lint-imports --config pyproject.toml`. Mypy from the repo root on changed files only: `backend/.venv/bin/mypy --config-file backend/pyproject.toml <files>`; **no NEW errors** vs `backend/mypy-baseline.txt` (mypy runs in CI only).
- Frontend commands from `frontend/`: `pnpm test:unit && pnpm test:node && pnpm lint && pnpm typecheck`.
- **Playwright project reality:** `chromium-desktop` has `testMatch: /admin-(shell|students|registrations)\.spec\.ts/` (`playwright.config.ts:79-84`) — a new `parent-*.spec.ts` will **not** run there. Do **not** widen that config. The parent spec runs on `chromium-mobile` (and `webkit-mobile` in CI); desktop-width coverage comes from the device matrix, which includes Galaxy Tab S4 plus an explicit 1280×800 desktop project added for this slice.
- `backend/v2/composition/admin.py` is at its 4800-line cap — this slice must not touch it. All composition work goes in `composition/parent.py` (2400 lines).
- No new frontend routes → **no** change to `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` or the route-count assertions. If an agent believes a route is needed, stop and report instead — do not add one.
- The parent shell is mobile-first and capped at `max-w-md` (`app/(parent)/layout.tsx:144`); `md:` is used nowhere in the parent tree. "Card layout below `md`" is therefore the shell's default — the requirement is met by building cards, not by adding breakpoints. `sm:` is the only prefix in use.
- Tap targets: `min-h-touch` / `min-w-touch` (44px, `tailwind.config.ts:6-16`). Every interactive element on the new card must clear 44px.
- Safe-area: do not change the sticky header classes; `frontend/app/shell-safe-area.test.ts` asserts the exact strings.
- Colours: Rally tokens only (`rally-*`, `status-*`). No new inline hex beyond what a touched file already carries.
- **No migration** in this slice. Do not add one.
- Keep every existing parent `data-testid` stable, notably `parent-dashboard`, `parent-progress`, `balance-autopay-optin`, `balance-payment-error`, `nav-calendar`, `nav-messages`, `messages-unread-badge`.

## Contract between backend and frontend (both agents rely on this — do not deviate)

```
GET /api/v2/parent/home           auth: require_persona("parent")
200 ->
{
  "children": [
    {
      "student_id": str,
      "full_name": str,
      "next_session": {                      # null when none upcoming
        "occurrence_id": str,
        "session_id": str,
        "session_title": str,
        "location": str | null,              # venue; null when unset
        "start_at": str,                     # ISO-8601 UTC instant
        "end_at": str,
        "coach_name": str | null             # ALWAYS null today — see decision 12
      } | null,
      "attendance_this_month": {
        "present": int,                      # status == "present"
        "total": int                         # every marked record this month
      },
      "latest_milestone": {                   # null when the child has none
        "kind": "note" | "skill",
        "label": str,                        # skill name, or the note's first line
        "at": str                            # ISO-8601 UTC instant
      } | null
    }
  ],
  "balance": {
    "amount_due_cents": int,                 # 0 when nothing is due
    "currency": str,                         # as stored, lowercase e.g. "usd";
                                             # the frontend uppercases for display
    "due_date": str | null,                  # earliest due_date among unpaid invoices
    "open_invoice_count": int,
    "payment_failed": bool                   # see decision 6b
  },
  "month_label": str,                        # e.g. "September" — academy-local
  "timezone": str                            # academy timezone, e.g. "America/Chicago"
}

The banner renders iff (balance.amount_due_cents > 0 or balance.payment_failed).

Errors: a non-parent caller gets **404**, not 403 — require_persona raises 404 so
route existence is never leaked (backend/v2/shared/http/persona.py:75-87). An
unauthenticated caller gets the usual 401 from get_auth_claims. Tests must assert
404 for the wrong persona.
A parent with no children returns {"children": [], "balance": {...zeros...}, ...}
with 200 — not 404.

Unchanged: /parent/children, /parent/enrollments, /parent/attendance,
/parent/progress, /parent/payments, /parent/invoices, /parent/credits,
/parent/waivers/current, /parent/academy, /parent/children/{id}/schedule,
/parent/students/{id}/skill-updates. No response shape changes anywhere.
```

---

### Task 1 (backend agent): `GET /api/v2/parent/home` aggregator + tests

**Files (create):**
- `backend/v2/interfaces/parent/home_routes.py` — one `GET /home` route, `response_model=ParentHomeResponse`, `claims: AuthClaims = Depends(require_persona("parent"))`, `use_cases: ParentUseCases = Depends(get_parent_use_cases)`. Follow `schedule_routes.py` exactly for imports, dependency order and the view-construction style. Call `use_cases.get_parent_home(parent_id=claims.user_id)` and map the result into views. No business logic in the route.

**Files (modify):**
- `backend/v2/interfaces/parent/router.py`: import `home_routes` and `router.include_router(home_router)`, keeping the alphabetical order of the existing block.
- `backend/v2/interfaces/parent/views.py`: add `ParentHomeNextSessionView`, `ParentHomeAttendanceView`, `ParentHomeMilestoneView`, `ParentHomeChildView`, `ParentHomeBalanceView`, `ParentHomeResponse` — field-for-field as the contract above. Mirror the naming/style of `ParentScheduleEntryView`.
- `backend/v2/interfaces/parent/deps.py`: expose `get_parent_home` on `ParentUseCases` alongside the existing entries.
- `backend/v2/composition/parent.py`: add `async def get_parent_home(*, parent_id: str) -> dict[str, Any]` near `get_child_schedule` (line ~2124). It must:
  - `children = await list_children_for_parent(parent_id)` — the ordering it returns is the card order (decision 8).
  - Resolve the academy timezone via `get_academy_info(academy_id=current_academy_id())` (`current_academy_id()` is the request-time tenant accessor used throughout this file — the "(C4)" comment convention); fall back to `"UTC"` when the field is missing or blank. Compute the current month's `[start, end)` **in that timezone**, then convert to the UTC instants used for comparison. `_local_period_label(instant, timezone_name)` already lives in this file at line ~2363 and does exactly this UTC→academy-local month conversion — **reuse it** rather than writing a fourth copy (its docstring already flags the existing triplication as issue #541). `month_label` is the month name in that timezone. Do not add a new dependency; `zoneinfo` is already in use.
  - Next session per child: `await get_child_schedule(parent_id=parent_id, student_id=..., frm=<today in academy tz>, limit=1, offset=0)` and take the first entry. The underlying use case already sorts ascending by `start_at` and defaults its window to `[now, now+30d]`, so entry 0 is the next session. Run the per-child fan-out with `asyncio.gather(..., return_exceptions=True)` and treat any exception as "no next session" for that child only (decision 11) — log it at warning with the student id, never propagate.
  - Attendance this month: **count, do not paginate** (decision 13). One `db["attendance"]` aggregation grouped by `student_id`, filtered on `academy_id`, `student_id: {"$in": [...]}` and `marked_at` within the academy-local month window, projecting a total and a present count per student. Mirror the filter style of the lifetime counters in `list_children_for_parent` (:1101-1110). Children with no rows get `{present: 0, total: 0}`. Do **not** call `list_attendance_for_parent`.
  - Milestone per child: one `list_progress_for_parent(parent_id, limit=..., offset=0)` call for the family, bucketed by `student_id` — it already applies the `visibility == "shared"` filter to `progress_notes` and blends `session_feedback`, and returns rows sorted `created_at` desc, so the first row per child is that child's newest. Pass a limit large enough to cover every child (the method fetches all matching rows internally and slices, so a generous limit is cheap). Plus the newest skill update per child via `student_progress.get_recent_skill_updates.execute(student_id)` — the same use case `progress_skill_routes.py:125-133` calls — fanned out with `asyncio.gather(..., return_exceptions=True)`. Compare the two candidates by timestamp; later wins. `label` for a note is its `body`'s first line trimmed to 80 chars; for a skill it is the skill name.
  - Balance: `invoices = await list_invoices_for_parent(parent_id)` (returns **all** invoices, unfiltered — the repo applies no status filter, so filtering is this method's job); `amount_due_cents = sum(i.balance_due_cents for i in invoices if i.status not in {"void", "paid"})`; `open_invoice_count` counts those same rows; `due_date` is the earliest `due_date` among them (null when none); `currency` is the first non-empty `currency` on those rows, defaulting to `"usd"` (`LedgerInvoice.currency` is lowercase). `payment_failed` per decision 6b: read `last_attempt_outcome` from `list_enrollments_for_parent(parent_id)` **and** port the payments rule from `frontend/lib/parent-home.ts` `findPaymentNeedingAttention` (`PAYMENT_ISSUE_STATUSES = {"failed","past_due","requires_payment_method"}`, suppressed when that payment's invoice has since become `paid` or `void`) using `list_payments_for_parent`. Read that TypeScript function before porting; do not invent a second definition.
  - Never raise because one child's leg failed. A parent with zero children returns empty children and a zeroed balance.
  - Tenancy: every filter must carry `academy_id` from `current_academy_id()` at call time, never a value captured at composition time.

**Tests (add):**
- `backend/v2/tests/interface/test_parent_home_routes.py` — new. Use the `_make_client` pattern from `test_parent_invoice_routes.py:178-199`: a fresh `FastAPI()`, `register_exception_handlers(app)`, `app.include_router(parent_router, prefix="/api/v2")`, `dependency_overrides[get_auth_claims]` returning `AuthClaims(user_id="parent-1", email=..., academy_id="acad", roles=("parent",))`, and `dependency_overrides[get_parent_use_cases]` returning a hand-written duck-typed fake exposing only `get_parent_home`. Cover: 200 shape with two children; a child with no upcoming session gets `next_session: null`; zero children returns `children: []` and a zeroed balance with 200; a **non-parent persona gets 404** (not 403 — see the contract); the response validates against `ParentHomeResponse`.
- Composition-level test beside whichever existing test already covers `list_progress_for_parent` with a Mongo fake (search `progress_notes` under `backend/v2/tests/composition` / `tests/integration` / `tests/unit/test_parent_composition.py` and put it there): a `get_parent_home` test seeding two students **linked by both `parent_id` and `parent_user_id`** (`_parent_students` matches either — cover both so a legacy-shaped student is not silently dropped), attendance rows inside and outside the month window, one shared and one private progress note, one skill update, and a mix of `open` / `partially_paid` / `paid` / `void` invoices. Assert: month bucketing uses the academy timezone (seed a record that falls in a different month under UTC than under `America/Chicago` and assert the academy-local answer); private notes never appear as a milestone; `amount_due_cents` includes `partially_paid` and excludes `paid` and `void`; the later of note-vs-skill wins as the milestone; attendance counts are not truncated by any 50-row page limit (seed more than 50 records in the month for one child).
- A failure-isolation test: make one child's schedule leg raise and assert the other child's card is still complete and the response is 200.

- [ ] Implement in the order listed; run ruff format/check, the full pytest suite (`-n auto`, must be green), import-linter, and mypy on every changed backend file (no new errors vs the baseline).
- [ ] Return: changed files, test counts, mypy delta, and the exact JSON body the route produces for a two-child fixture (so the orchestrator can diff it against the contract).

---

### Task 2 (frontend agent): kid-first Home, balance banner, Progress deep link, tests

**Files (modify/create):**
- **New** `frontend/lib/api/parent-home.ts` (or extend `lib/api/parent.ts` if the agent prefers one client file — pick one and say which): `getParentHome(): Promise<ParentHomeResponse>` → `GET /parent/home`, plus the TypeScript types mirroring the contract verbatim (`ParentHomeChild`, `ParentHomeNextSession`, `ParentHomeAttendance`, `ParentHomeMilestone`, `ParentHomeBalance`, `ParentHomeResponse`). Reuse `apiFetch` from `./client` exactly as the neighbours do.
- `frontend/lib/parent-home.ts` (407 lines, pure, already node-tested): add **pure** helpers for the new card, keeping `buildParentHomeModel` and `findPaymentNeedingAttention` intact because the rest of the page still uses them:
  - `shouldShowBalanceBanner(balance): boolean` — `amount_due_cents > 0 || payment_failed`.
  - `balanceBannerCopy(balance, formatMoney): { headline: string; detail: string }` — headline `"$120.00 due"`, detail `"Due Sep 12"`, or for the failed case headline `"Payment didn't go through"`, detail `"Update your payment method to stay enrolled."` Plain parent wording; no jargon, no invoice ids.
  - `attendanceCopy(a): string` — `"6 of 7 sessions this month"`, or `"No sessions marked yet this month"` when `total === 0`.
  - `nextSessionCopy(next, timezone): { when: string; where: string } | null` — `when` is day + time rendered in the **academy** timezone via the existing `resolveAcademyTimeZone` / `lib/format/academy-time` helpers (already imported by the dashboard); `where` is `location ?? "Venue to be confirmed"`.
  - `milestoneCopy(m): string | null` — `"<label> · <relative date>"`, null when no milestone.
  - Every one of these is exercised from `frontend/lib/parent-home.node-test.mjs` (node env, no DOM) — extend that file, do not create a parallel one.
- `frontend/app/(parent)/parent/dashboard/page.tsx` (629 lines) — the reorder:
  - Replace the nine `useQuery` calls with `useQuery({ queryKey: ["parent","home"], queryFn: getParentHome })` **plus** the existing `academyQuery` (still needed for `AcademyContact`) and the queries that the retained sections genuinely need: `RecentActivityCard` and `PrimaryActionCard` are built from `buildParentHomeModel`, so keep the queries those two consume (`enrollments`, `attendance`, `progress`, `payments`, `invoices`, `credits`, `waivers/current`, and `progress-summary` behind its flag) — do **not** delete them, they feed the sections that stay. The new endpoint replaces only the hero/metrics/next-class/latest-note reads.
  - Render order inside `<section data-testid="parent-dashboard">`:
    1. `BalanceBanner` — `data-testid="parent-balance-banner"`, rendered **only** when `shouldShowBalanceBanner`. Headline + detail from `balanceBannerCopy`, and exactly one action: a 44px `Link` to `/parent/payments` labelled `Pay` (`data-testid="parent-balance-pay"`). Amber/`status-amber-*` for money due, `status-red-*` for a failed payment. `role="status"` so it is announced.
    2. Child cards — a `<ul data-testid="parent-child-cards">` with one `<li>` per child. Each card `data-testid="parent-child-card-<student_id>"` is a single `Link` to `/parent/progress?child=<student_id>` wrapping: the child's name as the heading; a "Next session" row (day/time, venue, coach when present) or "No upcoming sessions"; an "Attendance this month" row from `attendanceCopy`; a "Latest milestone" row from `milestoneCopy` or "No milestones yet". Whole card ≥44px tall by construction; the card is the tap target, so no nested interactive elements inside it. Reuse the gradient-avatar convention already in `app/(parent)/parent/children/page.tsx:33-44` if an avatar is wanted — extract it to a shared module rather than copying the hash function.
    3. Zero children → the existing `RegistrationHero` (unchanged) and no card list.
    4. `IssueStrip` (unchanged), then `PrimaryActionCard` **only when** `model.primaryAction.kind !== "payment"`, then `RecentActivityCard`, `RequestsCard`, `AcademyContact` — all unchanged.
  - Delete `ProgressHero`, `MetricGrid`, `LatestNoteCard`, `NextClassCard` and the now-unused `selectedChildId` state. Remove imports that become unused (lint will catch them).
  - Loading: a card-shaped skeleton (`data-testid="parent-home-skeleton"`) while the home query is pending. Error: an inline message, not a blank page.
- `frontend/app/(parent)/parent/progress/page.tsx`: `SkillProgressSection` seeds its selected child from `useSearchParams().get("child")` — match by `student_id`, fall back to index 0 when the param is absent or unknown. Keep `activeChildIdx` as the internal state so the tab strip still works. The section must be reachable when a card links to it, so give it `id="skill-progress"` and have the dashboard link to `/parent/progress?child=<id>#skill-progress`. Wrap the `useSearchParams` consumer in a `<Suspense>` boundary if Next's build complains (it is a client page, but check).
- `frontend/app/(parent)/parent/children/page.tsx`: no behaviour change; only extract the shared avatar-gradient helper if task 2 chose to reuse it.

**Tests (add/extend):**
- `frontend/lib/parent-home.node-test.mjs`: cases for each new pure helper — banner shown/hidden across (due > 0, failed, both, neither); `attendanceCopy` at 0 total; `nextSessionCopy` null; `milestoneCopy` for note vs skill.
- **New** `frontend/e2e/specs/parent-home.spec.ts`, following `parent-self-service.spec.ts` exactly: import `test`/`expect` from `../fixtures/mock-api`, re-register `**/api/v2/me` with `roles: ["parent"]`, then `page.route` the parent endpoints. `mock-api.ts` has **no** parent stubs today, so every parent endpoint this page touches must be stubbed in this spec (including the ones feeding the retained sections, or those sections will hang). Cases:
  - **two children, no balance** — two `parent-child-card-*` present in the stubbed order, each showing next session, attendance and milestone; `parent-balance-banner` **absent**.
  - **one child, balance due** — banner visible with the amount and due date, `parent-balance-pay` links to `/parent/payments` and is ≥44px.
  - **payment failed, nothing due** — banner visible with the failed copy.
  - **zero children** — `RegistrationHero` visible, no card list, no banner.
  - **card deep-link** — clicking a card lands on `/parent/progress?child=st-2` and that child is the selected tab.
  - A11y: the banner has `role="status"`; each card is a single link with an accessible name containing the child's name; no horizontal overflow at 320px.

- [ ] Run `pnpm test:unit && pnpm test:node && pnpm lint && pnpm typecheck`, then `pnpm exec playwright test e2e/specs/parent-home.spec.ts e2e/specs/parent-self-service.spec.ts --project=chromium-mobile --reporter=line`. (`chromium-desktop` matches only three admin specs — if you pass it and zero tests run, report that; **do not** widen the config.)
- [ ] Return: changed files, the exact query keys and endpoints the page now calls, every test id added, and the test run summaries.

---

### Task 3 (orchestrator): review → fix → verify → release note → PR

- **Review (parallel, Opus):** (a) backend correctness — timezone month bucketing, the paid/void exclusion, failure isolation, tenancy, contract conformance; (b) frontend a11y/mobile — 44px, contrast, the card-as-single-link pattern, focus order, no overflow at 320px, no nested interactives; (c) test coverage both sides. Drop any finding with confidence < 0.7. Findings → fix agents → re-verify.
- **Verify (parallel):** backend suite + ruff + import-linter + mypy delta; frontend unit/node/lint/typecheck + the parent Playwright specs on `chromium-mobile`; then the **device matrix** — scratch config already staged at `<scratchpad>/devmatrix/playwright.device.config.ts`, pointing at this worktree's `playwright.config.ts`, projects iPhone SE / 12 / 14 / 14 Pro Max / 15 Pro on webkit, Pixel 5 / 7, Galaxy S9+ / S24 / Tab S4 on chromium, **plus a 1280×800 desktop chromium project** to replace the coverage `chromium-desktop` cannot give. Screens: `/parent/dashboard` with **0, 1 and 2 children** and **with and without a due balance** (six states), plus `/parent/progress?child=<id>`. Assert cards and the Pay button are ≥44px and inside the viewport, and no horizontal overflow. Screenshots kept in the scratchpad.
- **Release note** `docs/release-notes/2026-09-06-parent-home-kid-first.md` — the three exact sections, real PR number once it exists. Deploy note: **no migration**; the new route is additive and the old parent endpoints are unchanged, so backend and frontend can deploy in either order.
- Commit, check machine load (`uptime` load < 8 and `pgrep -f "playwright|next-server|next dev"` ≤ 1 — other worktrees run their own gates and a SIGTERM in gate output is contention, not a failure), push, open the PR against `main`, wait for **CI Gate** + **Release Notes Gate**, **ask the owner once before merging**, then watch the Production run and hand the owner the approval link (Production Approval is a user-only click). Confirm the smoke check afterwards.
- Update `/Users/ramc/.claude/projects/-Users-ramc-Documents-Code-academy-manager/memory/project_role_model_design_2026_09_04.md` when slice 4 lands.
