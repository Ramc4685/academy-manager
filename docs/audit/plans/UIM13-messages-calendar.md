# UIM13 — Real Messages inbox + Calendar (coach/parent)
Status: DONE (PR #375, 2026-07-28)
Size: L · Depends on: coordinates with UIC8 (shared-stub deletion) · Tracker: ../TRACKER.md

## User value
Admins already send broadcasts and DMs, but coaches and parents have nowhere to read them — the `(shared)/messages` and `(shared)/calendar` pages are shells. A real per-recipient inbox closes the send→read loop, and a merged calendar gives coaches/parents one schedule view instead of scattered lists.

## Backend status (verified)
**Messages — persistence already exists; recipient read routes do not.**
- Store: `backend/v2/shared/comms/messages.py` — `Message` model (`message_id, academy_id, kind: dm|announcement, sender_id, sender_persona, recipient_id (None for broadcasts), body, created_at, read_by: list[str], scope_*, ...`) persisted in the tenant-scoped `messages` collection via `MongoMessageRepository`.
- `MongoMessageRepository.for_recipient(recipient_id)` already returns that user's DMs + all announcements, newest first, limit 200. `read_by` exists but nothing writes to it yet.
- `CommsService` docstring says "used by admin/parent/coach BFFs alike", but only admin exposes routes: `GET /admin/messages`, `POST /admin/messages/broadcast`, `POST /admin/messages/dm` (`backend/v2/interfaces/admin/comms_routes.py:53,62,78`). Grep confirms **zero** `/messages` routes under `interfaces/coach/` or `interfaces/parent/`. Email campaigns (`POST /admin/campaigns`) are a separate email-only path — not inbox content.
- So Phase 1 is thin: new persona read routes over the existing store + a mark-read write, **not** a new read model.

**Calendar — pure composition of existing endpoints.**
- Coach: `GET /coach/sessions` — all upcoming sessions for the coach (`backend/v2/interfaces/coach/sessions_routes.py:15`, `CoachScheduleResponse`).
- Parent: `GET /parent/children` (`interfaces/parent/activity_routes.py:24`) + `GET /parent/children/{student_id}/schedule?from&to&limit&offset` (`interfaces/parent/schedule_routes.py:20`, `ParentScheduleResponse`). No new backend needed for calendar.

**Frontend stubs:** `frontend/app/(shared)/messages/` and `frontend/app/(shared)/calendar/` exist as shells. **UIC8 coordination:** if UIC8 has already deleted them, Phases 2–3 create new persona pages; if not, this item replaces the stubs and UIC8 becomes moot — settle which order in the tracker before starting.

## Backend to build (Phase 1 — one PR)
- `GET /coach/messages` and `GET /parent/messages` in new `interfaces/coach/messages_routes.py` / `interfaces/parent/messages_routes.py`, `require_persona(...)`, wrong-persona 404, calling `CommsService`/`MongoMessageRepository.for_recipient(claims.user_id)`. Persona-shaped view models (id, kind, sender persona, body, created_at, read flag derived from `read_by`).
- `POST /coach/messages/{message_id}/read` and parent equivalent — adds `user_id` to `read_by` (new small repo method `mark_read(message_id, user_id)`; idempotent `$addToSet`). Unread count can be derived client-side from the list; skip a dedicated count endpoint for v1.
- Register all new routes in `backend/v2/tests/unit/test_audit_inventory_manifest.py`.
- Tests: recipient scoping (user A cannot see user B's DMs; announcements visible to all), tenant scoping (inherited from `TenantScopedRepository`), mark-read idempotency, wrong-persona 404.

## Frontend to build
**Phase 2 — inbox pages (one PR):**
- Replace the messages stub with per-persona inbox pages (coach + parent; admin already has send UI — add its own read list only if trivially shared): list grouped by day, announcement vs DM styling, unread dot + badge in nav, mark-read on open (mutation + optimistic `read_by` update).
- Data layer: `frontend/lib/api/v2/messages.ts` via `apiFetch`; keys in `frontend/lib/query/keys.ts` (`coach.messages`, `parent.messages`); TanStack Query v5 with a modest `refetchInterval` (no push infra — polling is v1).

**Phase 3 — calendar (one PR):**
- Replace the calendar stub with a merged month/week schedule view:
  - Coach: render `GET /coach/sessions` entries on a calendar grid, day drill-down linking to the existing session pages.
  - Parent: fetch `GET /parent/children`, then `GET /parent/children/{id}/schedule` per child (parallel `useQueries`), color-coded per child, `from`/`to` bound to the visible range.
- Build the grid as a shared component (`frontend/components/` calendar) with persona-specific data adapters; no new endpoints.

## Implementation steps (phased; each phase one PR)
1. Phase 1 backend (routes + mark-read + manifest + tests).
2. Phase 2 inbox UI (coach + parent) + nav badges.
3. Phase 3 calendar UI composing the cited schedule endpoints.

## Files to change/create
- `backend/v2/shared/comms/messages.py` (mark_read), `backend/v2/interfaces/coach/messages_routes.py`, `backend/v2/interfaces/parent/messages_routes.py`, coach/parent `router.py` + deps wiring, `backend/v2/tests/unit/test_audit_inventory_manifest.py`.
- `frontend/lib/api/v2/messages.ts`, `frontend/lib/query/keys.ts`.
- `frontend/app/(coach)/coach/messages/page.tsx`, `frontend/app/(parent)/parent/messages/page.tsx` (or the `(shared)` location if kept), calendar pages per persona + shared calendar grid component; delete/replace `frontend/app/(shared)/{messages,calendar}` stubs per the UIC8 decision.

## Verification
- Backend tests above; import-linter green (shared/comms is already a shared module — no context-boundary issues).
- Manual: admin broadcast + DM → appear in coach and parent inboxes; mark-read persists across reload; second user doesn't see the DM.
- Calendar: coach entries match `/coach/sessions` list; parent multi-child ranges render and paginate via `from`/`to`.
- E2E: one happy-path spec per persona inbox; calendar smoke.

## Risks / rollback
- `for_recipient`'s 200-item cap and announcement fan-out (read state per user via `read_by` array) are fine at current scale; note a follow-up if academies exceed ~thousands of messages.
- Polling interval — keep ≥30s to avoid hammering.
- All phases additive; rollback = revert the phase PR (stubs can be restored from git if UIC8 ordering goes sideways).

## PR checklist (per phase)
- [x] Release note line — `docs/release-notes/2026-07-28-fix-uim13-messages-calendar.md`
- [x] TRACKER.md row updated (Status, PR/Issue)
- [x] This plan's Status → DONE (PR #NNN, date) after Phase 3

## Execution notes (2026-07-28)
All three phases shipped in a single branch/PR (`fix/UIM13-messages-calendar`)
rather than three, per the execution brief.

Deviations from the plan as written:
- The `(shared)/messages` and `(shared)/calendar` pages were **not** deleted.
  UIC8 (#327) had already converted them from stubs into role-aware redirect
  pages, so they were repointed at the new persona routes
  (`/coach/messages`, `/parent/messages`, `/coach/calendar`,
  `/parent/calendar`) instead of removed. Deleting them would have churned
  the QA route manifest for no user-visible gain.
- The calendar grid reuses FullCalendar via a new shared
  `frontend/components/calendar/PersonaCalendarView.tsx`, mirroring the
  existing `components/admin/AdminCalendarView.tsx` (dynamic import,
  `ssr: false`) rather than introducing a hand-rolled grid.
- No dedicated unread-count endpoint, per the plan — the badge derives the
  count client-side from the list query, which both persona layouts share
  with the inbox page via the same TanStack Query key.
