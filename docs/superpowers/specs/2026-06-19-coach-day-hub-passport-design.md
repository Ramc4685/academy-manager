# Coach Day Hub And Passport Design

## Purpose

Redesign the coach experience so the first screen is about coaching work:
sessions, attendance, skill focus, and parent communication. Coach pay must not
appear on the home screen. Coach pay belongs under Profile as "Pay & statements".

This design also keeps the coach Skill Passport page and includes fixing the
current passport loading failure.

## Current Behavior Found

- `frontend/app/(coach)/coach/dashboard/page.tsx` shows coach metrics including
  `Expected cut`, which makes money visible on the coach home page.
- `frontend/app/(coach)/coach/students/[studentId]/passport/page.tsx` calls
  `getStudentPassport()` and shows "Could not load passport" on failure.
- `frontend/lib/api/curriculum.ts` calls
  `/api/v2/coach/students/{student_id}/passport`.
- `backend/v2/interfaces/coach/skill_routes.py` already defines
  `GET /api/v2/coach/students/{student_id}/passport` and is mounted through
  `backend/v2/interfaces/coach/router.py`.
- Existing coach teaching-plan and skill-board work can provide skill focus
  inputs, but the coach home needs a clearer day-level read model.
- Existing messaging primitives and admin messages exist, but dedicated
  coach/parent scoped inbox routes are not present in the checked source.

## Approved Direction

Use the **Coach Day Hub** approach.

The coach home is a date-aware whole-day overview. It summarizes the selected
day and links into dedicated workspaces. It does not perform inline skill edits
and does not show coach pay.

## User Experience

### Coach Home

The home screen shows:

- Date selector: previous day, next day, Today, Tomorrow, This week, and a
  calendar picker.
- Day summary: session count, student count, attendance state, skill focus
  count, and parent-message signals.
- Session cards for the selected date.
- Session cards show grouped skill gaps by default, for example:
  "Backhand clear: Nethra, Aarav, Riya".
- Each session card links to:
  - Open session.
  - Prepare / teaching plan.
  - Open skill updates.
  - Message parents.
  - I can't attend.

Home is read-only for skill progress. It summarizes what matters and sends the
coach to the correct focused workflow.

### Session Workspace

The session workspace remains the coach's on-court operating screen.

It includes:

- Attendance.
- Prepare / teaching plan.
- Skill focus.
- Messages.
- Skill Passport drill-down links.
- Absence notice action for future assigned sessions.

### Prepare Before Class

Coach prep should reuse the already-coded teaching-plan and lesson-card flow.

Existing coach route:

```text
/coach/today/plan?date=YYYY-MM-DD
```

Existing backend routes:

```text
GET /api/v2/coach/today/plan?date=YYYY-MM-DD
GET /api/v2/coach/sessions/{session_id}/teaching-plan
```

The current implementation renders lesson cards with lesson number, goal,
teaching points, equipment, activity, safety notes, YouTube links, PDF citation
chips, and per-student focus rows. The Day Hub should link to this as
**Prepare** or **Teaching plan** from each session card and selected-date
summary.

If the coach needs a standalone browseable skills library outside assigned
sessions, that is not currently present in the checked coach UI. The existing
lesson-card library management is admin-only under the pathway screen. This
design keeps coach prep session-centered for this slice and does not add a
new coach-wide curriculum library unless it is separately approved.

### Session Skill Update Workspace

Skill updating happens in a separate session workspace, not on Home.

Route shape:

```text
/coach/sessions/{occurrence_id}/skills?date=YYYY-MM-DD
```

The workspace supports two update modes:

- **Update by skill:** select one skill, see all students in the session who
  need that skill, and apply a status update to all or selected students.
- **Update by student:** select one student, see that student's top gaps or
  full skill list, and update individual skill statuses.

The full Skill Passport remains available as a detailed student drill-down.

### Skill Passport

Keep:

```text
/coach/students/{student_id}/passport
```

The passport page is the full per-student skill detail page. The current
loading/404 problem is in scope for implementation and should be fixed rather
than hidden as a normal empty state.

### Parent Communication

The coach experience needs both:

- Individual parent messaging from a student/session context.
- Session-level parent broadcast/update as a secondary action.

The design should reuse the existing message storage/service where possible,
but expose coach and parent persona-scoped BFF routes. A coach may message only
parents of students in that coach's assigned sessions.

### Coach Absence Notice

The coach can mark "I can't attend" for an assigned future session. This creates
an admin-visible replacement-needed signal so the admin can use the existing
replacement coach workflow.

This slice does not add coach self-present check-in.

### Coach Pay

Coach pay is not shown on Home.

Pay lives under:

```text
/coach/profile
```

as a "Pay & statements" section.

## Backend Design

Add or reshape coach BFF endpoints around coach workflows.

### Day Hub Read Model

```text
GET /api/v2/coach/day-hub?date=YYYY-MM-DD
```

Response includes:

- Selected date.
- Day summary.
- Sessions for the date.
- Roster counts.
- Attendance state.
- Grouped skill gaps by session.
- Top 2-3 gaps per student for the toggle/detail view.
- Parent-message signals.
- Absence notice state.

The backend owns the business truth. The frontend should not infer skill gaps,
tenant access, or messaging eligibility.

### Session Skill Read Model

```text
GET /api/v2/coach/sessions/{occurrence_id}/skills?date=YYYY-MM-DD
```

Response includes:

- Session identity, occurrence identity, and selected date.
- Roster.
- Skill groups.
- Per-student top gaps.
- Existing skill statuses.
- Enough IDs for by-skill and by-student updates.

### Bulk Skill Update

```text
POST /api/v2/coach/sessions/{occurrence_id}/skills/bulk-status
```

Request includes:

- `skill_id`
- `program_id`
- `level_id`
- selected `student_ids`
- new status
- session/date context

The existing single-student endpoints remain valid:

```text
POST /api/v2/coach/students/{student_id}/skills/{skill_id}/status
POST /api/v2/coach/students/{student_id}/skills/{skill_id}/test
```

### Passport

Keep and verify:

```text
GET /api/v2/coach/students/{student_id}/passport
```

The implementation should investigate why the browser receives 404 even though
the route exists in source.

### Messaging

Add coach/parent persona-scoped routes over the existing message capability.
Use these initial route shapes unless implementation discovery finds an existing
equivalent route that should be reused:

```text
GET /api/v2/coach/messages
POST /api/v2/coach/messages/direct
POST /api/v2/coach/sessions/{occurrence_id}/messages/broadcast
GET /api/v2/parent/messages
POST /api/v2/parent/messages/{thread_id}/reply
```

The contract must support:

- List coach threads/messages relevant to assigned students.
- Send an individual parent message from student context.
- Send a session parent update/broadcast to parents in an assigned session.
- Parent can read and reply in a parent inbox.

Authorization must return 404 for unrelated students, sessions, or parents.

### Absence Notice

Add a coach route for future assigned dated occurrences:

```text
POST /api/v2/coach/session-occurrences/{occurrence_id}/absence-notice
```

The backend validates the coach is assigned to that occurrence and records a
replacement-needed signal visible to admin.

## Frontend Design

### Files Likely Affected

- `frontend/app/(coach)/coach/dashboard/page.tsx`
- `frontend/app/(coach)/coach/sessions/[id]/page.tsx`
- New session skills route under `frontend/app/(coach)/coach/sessions/[id]/`
- `frontend/app/(coach)/coach/students/[studentId]/passport/page.tsx`
- `frontend/app/(coach)/coach/profile/page.tsx`
- `frontend/lib/api/coach.ts`
- `frontend/lib/api/curriculum.ts`
- Coach messaging client additions, likely in `frontend/lib/api/coach.ts` or a
  focused communications client.

### Theme

Use the current application and coach theme. Do not introduce a new visual
language. Keep coach screens lightweight, mobile-first, and consistent with the
existing coach shell.

### Error Messages

Errors must be clean and coach-readable. Do not show raw API paths, stack
traces, `404`, `500`, or internal codes in user-facing text.

Examples:

- "Couldn't load skill passport. Try again."
- "Couldn't save skill update. Check your connection and retry."
- "You can only message parents from your assigned sessions."
- "Couldn't send absence notice. Try again."

Internal codes may be logged or used for tests, but not surfaced directly in
the UI copy.

## Error And Empty States

- No sessions on selected date: show a clean empty state and keep date controls.
- Skill focus unavailable: show session cards and attendance; show "Skill focus
  unavailable" with retry.
- Passport load failure: show retry and treat 404 as a bug to investigate.
- Messaging unrelated parent: backend returns 404; UI shows clean permission
  message.
- Absence notice on unassigned session: backend returns 404; UI shows clean
  failure message.
- Absence notice after replacement already exists: show current replacement or
  replacement-request status; do not duplicate.
- Offline: allow cached reads where already supported, but do not queue skill,
  message, or absence writes in this slice.

## Risks

- The passport 404 may be caused by a stale local server, frontend BFF proxy
  configuration, or deployed backend mismatch rather than missing source code.
- Messaging primitives are too thin for a polished coach/parent inbox; scoped
  routes and relationship validation are required.
- Bulk skill update must avoid accidentally updating students outside the
  assigned session.
- Day Hub could become too heavy if it returns full passport data. It should
  return summaries and link to detail routes.
- Future session skill focus depends on having enough roster/pathway data for
  that date.

## Verification Plan

Backend:

- Interface tests for `GET /coach/day-hub`.
- Interface tests for `GET /coach/sessions/{id}/skills`.
- Interface tests for bulk skill update.
- Regression tests for coach passport route.
- Messaging authorization tests: assigned parent allowed, unrelated parent 404.
- Absence notice tests: assigned future session allowed, unassigned 404,
  duplicate/replacement state handled.
- Wrong persona 404 tests for coach routes.

Frontend:

- `pnpm typecheck`
- `pnpm lint`
- Mobile browser check for:
  - Date selection and future sessions.
  - Home summary without pay.
  - Separate session skill-update workspace.
  - By-skill update mode.
  - By-student update mode.
  - Skill Passport load/retry.
  - Message parent entry points.
  - "I can't attend" action.
  - Profile Pay & statements placement.

Ledger:

- Record focused verification in
  `docs/test-results/active/2026-06-18-coach-experience-passport-redesign.md`.
