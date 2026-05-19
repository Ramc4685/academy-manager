# Rally Admin — Shell + Settings + Page Restyles Design

**Date:** 2026-05-19
**Author:** Claude (brainstorm with user)
**Status:** Design — awaiting user review before implementation plan
**Parent plan:** `~/.claude/plans/piped-zooming-stonebraker.md` (Phases 0–3 already executed; this spec covers Phases 4–9)

## Context

The user shared the Rally Academy mockup at `/Users/ramc/Downloads/Badminton Academy Manager/` and asked for the admin persona on `frontend/` to be brought to Rally parity, single-frontend going forward.

Phases 0–3 of the parent plan are mostly committed on branch `feat/rally-admin-foundation`:
- **Phase 0** (committed `53abb75`): Rally design tokens + 10 `components/ds/*` primitives ported under canonical `frontend/`.
- **Phase 2** (committed `5d151e7`): Rally dark slate sidebar shell (`(admin)/layout.tsx`), `screen-meta.ts` route metadata, `admin-action-slot.tsx` context provider.
- **Phase 3 (in-flight, uncommitted):** Dashboard, Sessions list, Sessions detail, Payments (promoted from `billing/page.tsx`), Comms → Messages rename + restyle, `(shared)/messages` link update, Playwright `admin-shell.spec.ts` (10/12 tests passing on a non-colliding port; 2 failures resolved with drawer-open assertion + one screenshot revealed a runtime null-access bug — see bug fix below).

This spec covers what comes next: a one-time approval for the remaining arc (shell stays, Settings deep dive, restyle remaining 12 pages, route cleanup, verification handoff). The user explicitly wants:
- **Sidebar layout retained** (top-tabs idea was raised then rejected).
- **All 7 Settings panels** visible in the UI; backed by real data where possible, "Coming next" Rally cards where not.
- **Approve the full design once, execute over multiple sessions** with terse per-session reports.

## Goals

1. Close out Phase 3 cleanly (hotfix + commit + spec test passes on free port).
2. Build a Rally Settings page with 7 panels: 5 fully real + read-only Gateway + 1 fully Coming-next (Branding) + Data panel partial.
3. Restyle the 12 remaining admin pages to Rally aesthetics, preserving every BFF call and action.
4. Reconcile the route map: rename completed in Phase 3 (`comms` → `messages`); delete `admin/billing/`, `admin/comms/`, and possibly `admin/finance/` after replacements verified.
5. Add the additive backend endpoints needed for Settings (4 new, all under `backend/v2/interfaces/admin/`).
6. Land a Playwright smoke spec covering the full Rally admin map.
7. Update `test_result.md` with the verification matrix + remaining risks per AGENTS.md.

## Non-goals

- Dashboard "Needs your attention" endpoint + section (deferred — no real attention endpoint exists).
- Branding storage backend (file uploads, object storage). Branding panel ships as Coming-next.
- Data deletion / GDPR account-removal flow (Coming-next).
- Stripe Connect onboarding write flow (Gateway panel is read-only this arc).
- Rich Students filtering (search / pagination / status / group). Phase 6+ work.
- Backend context creation (no new DDD contexts).
- Legacy `frontend-next` directory work (does not exist on current `main`).
- Production deploy.

## Out-of-scope but adjacent (named so they don't sneak in)

- New generic CRUD endpoints. Each new endpoint stays admin-persona-shaped under `/api/v2/admin/*`.
- Endpoint-behavior changes disguised as DTO enrichment (filters, pagination, search). Those are separate follow-on phases.
- Coach / parent route restyles. Only admin in this arc.

## Sidebar shell — already shipped (no rework)

Reference: `frontend/app/(admin)/layout.tsx` (committed `5d151e7`).
- Dark slate-900 sidebar, 240px desktop, 3 nav groups WORK / MONEY / COMMS · OPS.
- Brand block top with ShuttleMark + "Rally Academy / ADMIN · COURT 7".
- User pill bottom with `Avatar` from `usePersonaAuth("admin")`.
- Active state: slate-800 row + volt-yellow left border + volt-yellow icon tint.
- Mobile drawer (`<lg`) opens via topbar hamburger.
- Topbar: title + subtitle + breadcrumbs from `SCREEN_META`, plus `<AdminActionSlot />`, plus offline pill + SW update button.

## Settings page — 7-panel Rally design

File: `frontend/app/(admin)/admin/settings/page.tsx` (rewrite). Each panel is its own client component under `frontend/components/admin/settings/`.

### Tab strip

Horizontal Rally pill tabs across the top of the Settings page (NOT a layout-level tab strip — local to this page only). Tabs use mono-uppercase labels with `tracking-chip`. Active tab: cobalt background + white text. Inactive: slate ink on slate-paper.

URL state: `?panel=academy|fees|gateway|notify|roles|branding|data` (default `academy`). Shallow update on tab click. Refresh-safe.

### Panel matrix

| Panel | Status | Frontend file | Backend work |
|---|---|---|---|
| **Academy** | Real read/write | `academy-panel.tsx` | `GET/PATCH /api/v2/admin/academy` — display name, timezone, contact email, hours, address. Reads/writes academy doc with optional fields. |
| **Fees** | Real read/write | `fees-panel.tsx` | `GET/PATCH /api/v2/admin/academy/fees` — default_monthly_cents, late_fee_cents, grace_days. Sub-document on academy. |
| **Gateway** | Real **read-only** | `gateway-panel.tsx` | `GET /api/v2/admin/academy/gateway` — returns `{ stripe_connected: bool, stripe_account_id_masked: str \| null, manual_methods: string[] }`. No write endpoint (Stripe Connect onboarding is a separate workstream). UI shows "Connected to Stripe" with masked ID, or "Not connected — onboarding deferred". |
| **Notify** | Real read/write | `notify-panel.tsx` | `GET/PATCH /api/v2/admin/academy/notifications` — toggles for dues_reminders, attendance_alerts, daily_digest_to_admin. Drives existing scheduler. |
| **Roles** | Real read/write | `roles-panel.tsx` | Reuse existing `GET /api/v2/admin/users` for list. New `PATCH /api/v2/admin/users/{user_id}/role` to change a user's role (admin-only). Invite-new-admin = email-input form posting to `POST /api/v2/admin/users/invite` (new). |
| **Branding** | **Coming-next** | `branding-panel.tsx` | None. Logo upload + primary color + email signature require object-storage backend. Renders Rally `Card` with `Overline` "Coming next" + honest copy + no fake fields. |
| **Data** | Partial — exports real, deletion Coming-next | `data-panel.tsx` | Reuse existing `GET /api/v2/admin/reports/*.csv` endpoints; render as a download list. Deletion section is Coming-next. |

### Save UX

Each writable panel uses TanStack Query with a `useMutation` save handler. Dirty detection by shallow diff against the original payload. Save button: `Button variant="volt"` when dirty, `Button variant="secondary" disabled` when clean. Success: inline `Alert tone="green"` for 2s + query invalidate. Error: `Alert tone="red"` with the BFF error message.

### Coming-next card spec

- Rally `Card p={32}` with `Overline children="Coming next"`.
- Display heading (Outfit, 18px, `tracking-[-0.01em]`).
- One-sentence honest explanation of what needs backend work and why it's deferred.
- No mock fields. No fake values. No links to nowhere — leave the card as a passive empty state.

## Restyles — 12 remaining pages

Pattern for every page: read the file, identify data hooks + mutations, replace generic Tailwind chrome with Rally primitives (`Card`, `Chip`, `Button`, `LaneHeader`, `Avatar`, `BigNum`, `Overline`), preserve every handler, add `data-testid` markers. No fake fields. Where the mockup shows a field the BFF doesn't return, omit it.

### WORK group

- **`students/page.tsx`** — table restyle. Avatar + name, dues `Chip`, attendance fill bar. Wires to existing `listAdminStudents`.
- **`users/page.tsx`** — directory restyle. Role `Chip` (admin/coach/parent), Avatar, last-active.
- **`waitlist/page.tsx`** — list restyle. Mono position number, status `Chip`, promote/skip/remove actions.
- **`pause-requests/page.tsx`** — approval queue. `Chip` for status, Approve/Decline buttons.

### MONEY group

- **`dues/page.tsx`** — outstanding-by-parent. Mono tabular amounts, `Chip` for follow-up stage, "Send reminder" via existing endpoint.
- **`expenses/page.tsx`** — currently an alias to `/admin/finance`. Promote real implementation from `finance/page.tsx`'s expenses section, restyle with categorize chips + create-modal. Wires `/admin/finance/expenses`.
- **`payouts/page.tsx`** — currently an alias. Promote payouts section from `finance/page.tsx`. Wires `/admin/finance/payouts`.
- **`coach-payslip/page.tsx`** — per-coach earnings cards with `BigNum` + period chips.
- **`reports/page.tsx`** — CSV export tiles for each report + small `MiniBars` revenue chart.

### COMMS · OPS group

- **`audit-logs/page.tsx`** — mono actor + timestamp + action chips.

### `finance/page.tsx` fate

Once expenses + payouts + reports are real Rally pages, the original `finance/page.tsx` becomes redundant. **Default: delete in Phase 7 cleanup.** If during execution the user opts for a "Money overview" landing instead, it becomes a Rally KPI dashboard with cards linking to the splits. Confirm during the C3 commit.

### Per-page commit hygiene

- One commit per Rally sidebar group, not per page (3 restyle commits total).
- Commit message lists pages touched + any DTO gaps surfaced for Phase 6 backlog.
- DTO gaps default to omitted fields, not faked.

## Backend additions

Five small additive endpoints, all under `backend/v2/interfaces/admin/`:

| Endpoint | Verb | Auth | Use case | Notes |
|---|---|---|---|---|
| `/admin/academy` | GET | admin | Read academy doc | Returns display name, timezone, contact_email, hours, address. Optional fields default to nulls. |
| `/admin/academy` | PATCH | admin | Write academy display fields | Partial update; pydantic model with optional fields. |
| `/admin/academy/fees` | GET / PATCH | admin | Read/write fee config | Sub-document on academy: `default_monthly_cents`, `late_fee_cents`, `grace_days`. |
| `/admin/academy/gateway` | GET | admin | Read Stripe / manual gateway status | No write. Masks Stripe account ID. |
| `/admin/academy/notifications` | GET / PATCH | admin | Read/write notify toggles | Sub-document on academy: `dues_reminders`, `attendance_alerts`, `daily_digest_to_admin`. |
| `/admin/users/{user_id}/role` | PATCH | admin | Change a user's role | Validates target user is in same academy. Returns updated `AdminUserView`. |
| `/admin/users/invite` | POST | admin | Invite new admin | Body: `{email, role}`. Sends invite via existing comms infrastructure or returns invite token for manual share. Defer if comms infra not ready — Coming-next on UI side. |

### Architecture

- **Domain:** No new domain entities. Settings config is application-layer concern over the existing identity/billing contexts.
- **Application:** New use cases under `backend/v2/contexts/identity/application/` for academy read/write; reuse existing identity context for user-role changes. Fees + notifications config could live in identity or billing — pick during implementation based on which context already touches the academy doc most.
- **Infrastructure:** Reuse existing Mongo academy collection. Fees/notifications config are nested fields, no new collections.
- **Interfaces:** New `backend/v2/interfaces/admin/academy_routes.py` for academy + fees + notifications + gateway. Extend existing `directory_routes.py` for role-change endpoints.
- **Tests:** Contract tests under `backend/v2/tests/contract/` per endpoint. Use-case tests under `backend/v2/tests/application/` for new code paths. Interface tests under `backend/v2/tests/interface/` for HTTP behavior.

### Frontend API client

Extend `frontend/lib/api/admin.ts` with new types + functions (~80 LOC):
- `AdminAcademyView` + `getAdminAcademy()` + `updateAdminAcademy(payload)`.
- `AdminFeesView` + `getAdminFees()` + `updateAdminFees(payload)`.
- `AdminGatewayView` + `getAdminGateway()`.
- `AdminNotificationsView` + `getAdminNotifications()` + `updateAdminNotifications(payload)`.
- `updateAdminUserRole(userId, role)` + `inviteAdminUser(email, role)`.

## Commit sequencing (5 sessions)

| # | Commit | Files | Session |
|---|---|---|---|
| **A0** | hotfix: defensive null on dashboard KPIs | `admin/page.tsx` | this session |
| **A1** | Phase 3 close-out: commit current restyles + admin-shell.spec | `admin/sessions/`, `admin/payments/`, `admin/messages/`, `(shared)/messages`, `screen-meta.ts`, `e2e/specs/admin-shell.spec.ts` | this session |
| **B1** | Settings: 7-tab Rally chrome + Academy panel + endpoint | `admin/settings/page.tsx`, `components/admin/settings/academy-panel.tsx`, backend academy routes, contract test | session 2 |
| **B2** | Settings: Fees + Notifications panels + endpoints | `fees-panel.tsx`, `notify-panel.tsx`, backend additions, tests | session 2 |
| **B3** | Settings: Gateway (read-only) + Roles panels + endpoints | `gateway-panel.tsx`, `roles-panel.tsx`, role-PATCH + invite, tests | session 3 |
| **B4** | Settings: Data + Branding Coming-next | `data-panel.tsx`, `branding-panel.tsx` | session 3 |
| **C1** | WORK pages restyle: students + users + waitlist + pause-requests | 4 page files | session 4 |
| **C2** | MONEY pages restyle: dues + reports + coach-payslip | 3 page files | session 4 |
| **C3** | Finance split: expenses + payouts + finance roll-up decision | `expenses/page.tsx`, `payouts/page.tsx`, `finance/page.tsx` | session 5 |
| **C4** | OPS pages restyle: audit-logs | 1 page file | session 5 |
| **D1** | Phase 6 DTO enrichment (only if surfaced): optional `coach_name` on AdminSessionView | backend `views.py` + `sessions_routes.py` + tests | session 5 or follow-on |
| **D2** | Route cleanup: delete `admin/billing/`, `admin/comms/`, possibly `admin/finance/` | directory deletes + final link sweep | session 5 |
| **D3** | Playwright admin-shell.spec expansion + test_result.md handoff | `e2e/specs/admin-shell.spec.ts`, `test_result.md` | session 5 |

**5-session estimate.** User approves the spec once; each session executes its slice, commits, reports back with verification output. User only re-engages for sub-decisions (e.g. finance fate at C3, or DTO field naming).

## Verification

### Per commit
- `cd frontend && pnpm typecheck` clean.
- `cd frontend && pnpm build` succeeds; admin landing chunk < 300 KB.
- New endpoints: `pytest backend/v2/tests/{contract,application,interface} -k <feature>` clean.
- Playwright admin-shell smoke spec: passes on a non-colliding port (`PLAYWRIGHT_PORT=3801`).

### End-of-arc
- `cd backend && source .venv/bin/activate && pytest v2/tests` — no regressions.
- `cd frontend && pnpm exec playwright test` — full suite, no coach/parent regressions.
- Manual smoke at `http://localhost:3001/admin` (real dev server): sidebar renders, each nav leaf navigates without 404, no app-level console errors. Cross-persona smoke at `/coach/today` + `/parent/dashboard`.
- `test_result.md` updated per AGENTS.md feedback-loop: changed files per session, routes renamed, new DTO fields, backend additions, verifications performed + skipped, benign-warning ignore-list, remaining risks.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| User reverses a settled decision mid-arc (e.g. settings panel structure) | Capture choices in this spec; refer back rather than re-asking. |
| Stripe Connect onboarding leaks scope into Gateway panel | Hard-rule: Gateway is read-only this arc. Onboarding is a separate workstream with its own approval. |
| Branding panel pressure to add a quick logo upload | No. Branding is Coming-next. File-upload backend gets its own design + approval. |
| Finance roll-up dispute at C3 | Default = delete after splits land. Confirm in C3 commit before deleting. Easy to keep as a Money overview if user prefers. |
| Playwright port collisions with other worktrees | Run with `PLAYWRIGHT_PORT=<free>` env. Document in `test_result.md`. |
| DTO gaps surface that need new fields | Queue for Phase 6 D1 commit; additive optional fields only, no endpoint behavior changes. |
| `coach_name` lookup causes N+1 queries | Batch the lookup in the admin sessions BFF use case (single `find({_id: {$in: [...]}})` over coach IDs). Covered by a contract test asserting field presence. |

## References

- Mockup: `/Users/ramc/Downloads/Badminton Academy Manager/` — read-only.
  - Settings: `assets/admin-comms-screens.jsx:402-770`.
  - Sidebar: `assets/admin-screens.jsx:32-189`.
  - Design system: `assets/ds.jsx`.
- Parent plan: `~/.claude/plans/piped-zooming-stonebraker.md`.
- AGENTS.md feedback-loop section (project rules).
- Existing BFF: `backend/v2/interfaces/admin/` (13 route files), `backend/v2/contexts/{identity,enrollment,coaching,billing,onboarding}/`.
- Existing API client: `frontend/lib/api/admin.ts` (505 lines on main).
