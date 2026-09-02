# Admin / Owner Coverage of the Coach View — Design

**Date:** 2026-09-02
**Status:** Approved for implementation (production enhancement, requested as urgent)
**Supersedes:** the "rejected alternative" note in
`2026-07-09-admin-coach-toggle-and-parent-invite-design.md`

---

## Problem

Coaches get a personalised coach app: `/coach/today` lists only the
occurrences where they are the scheduled, actual, or substitute coach, and
every coach route is guarded by `require_persona("coach")` plus an
"assigned to this session" check.

The academy owner and admins need to step into that same view for **any**
session — see the roster the coach sees, mark or correct attendance, add a
progress note, post an announcement — when a coach forgets, is late, or is
absent. Today an admin gets a 404 on every coach route (wrong persona) and
the admin session page has no attendance surface at all.

The July design deliberately chose "real dual roles, no impersonation".
That solves the admin-who-also-coaches case but not this one: an owner is
not the assigned coach of most sessions, so granting them the coach role
still shows an empty Today page.

## Decision

**Supervisor access on the coach surface.** A user whose academy membership
carries `admin` or `owner` is a *coach supervisor*. Supervisors may use the
coach BFF and the coach app; on that surface they see **every** session in
the academy and pass every "assigned to this session" check. Writes keep the
real actor: attendance rows are `marked_by` the admin's own user id, and
corrections are recorded with `actor_role="admin"` (which already skips the
48-hour coach correction window).

No impersonation, no "view as coach X": the admin acts as themselves with a
wider scope. That keeps audit attribution truthful and needs no new identity
plumbing.

### Why not the alternatives

- **Attendance panel on the admin session page.** Duplicates the coach UI
  (roster, marks, notes, announcements, skills) that already exists and is
  tested, and would drift from it. The user explicitly asked to "see the
  coach's view".
- **Auto-grant `coach` role to admins.** Does not widen scope; they would
  still only see sessions assigned to them.
- **"View as coach" impersonation.** Attribution becomes wrong (marks would
  appear to come from the coach) and it needs a picker + audit story that
  this request does not need.

## Backend

### Guard

`backend/v2/shared/http/persona.py` gains:

- `COACH_SUPERVISOR_ROLES = ("admin", "owner")`
- `is_coach_supervisor(claims) -> bool` — true when any supervisor role is
  in `claims.roles` (academy-scoped roles only; platform roles do not count).
- `require_coach_surface()` — a dependency that admits `coach` **or** a
  supervisor role and 404s everyone else, exactly like `require_persona`.

Every route file under `backend/v2/interfaces/coach/` switches from
`require_persona("coach")` to `require_coach_surface()`. Parents and
students still get 404 on every coach route.

### Scope widening (reads)

`SessionOccurrenceRepository` (enrollment context) gains two tenant-wide
queries, mirroring the coach-scoped ones without the coach filter:

- `list_on_date(*, on_date)` — widened UTC window, non-cancelled, sorted.
- `list_upcoming(*, now, limit)`.

`ListCoachOccurrencesForDate.execute_for_academy(on_date)` and
`ListCoachUpcomingOccurrences.execute_for_academy(now, limit)` wrap them and
reuse the existing hydration + local-date narrowing. Hydrated rows now carry
`coach_id` (the session's primary coach) so callers can label sessions.

`GET /coach/today` and `GET /coach/sessions` branch on
`is_coach_supervisor(claims)`: supervisors get the academy-wide list, coaches
get the unchanged personal list. For supervisors the response also carries
`coach_id` and `coach_name` per session (resolved through a new optional
`resolve_user_names` callable on `CoachUseCases`), so the admin can tell
whose class they are looking at. Coaches see `coach_id` populated and
`coach_name` null (no extra lookup on the coach path).

### Scope widening (assignment checks)

`CoachAssignedSessionLookup.is_coach_assigned(coach_id, session_id)` is the
single choke point used by every route-level and use-case-level assignment
check (roster, notes, feedback, announcements, skills, teaching plan,
billing-enrollment reads). It gains an optional `is_supervisor` callable:

```
session exists in this tenant
  and (session.coach_id == coach_id or await is_supervisor(coach_id))
```

The tenant-scoped session lookup stays first, so a supervisor still cannot
touch a session from another academy. Composition wires `is_supervisor` to a
membership lookup on `academy_memberships` for `(current_academy_id(),
user_id)` — the same row `load_auth_claims` derived `claims.roles` from — and
returns true when that active membership carries a supervisor role. The extra
query runs only when the direct assignment test fails.

### Attendance use cases

`MarkAttendance.execute` and `BulkMarkAttendance.execute` accept
`supervisor: bool = False` (keyword-only). When true the "coach is one of
scheduled / actual / substitute" check is skipped. Occurrence existence,
session-id match, cancellation, enrollment, and conflict checks are
unchanged. The idempotency key still includes the actor's user id.

`PATCH …/attendance/{student_id}` passes `actor_role="admin"` for
supervisors, which the existing `CorrectAttendance` already treats as
"no assignment check, no correction window".

### Not widened (deliberately)

- Coach roster add/remove stay disabled (already 403 for everyone).
- `/coach/dashboard` metrics, `/coach/profile`, `/coach/messages` remain
  keyed on the caller's own user id. An admin sees their own (usually empty)
  dashboard; this is acceptable for a supervision surface and avoids
  recomputing academy-wide metrics that the admin dashboard already shows.
- Billing enrollment *moves* from the coach surface: the read path passes
  through the widened lookup, but the design does not add tests or UI for an
  admin performing moves from the coach app; admins do that in the admin app.

## Frontend

- `lib/api/me.ts`: `COACH_SUPERVISOR_ROLES`, `canSuperviseCoaching(roles)`,
  and `availablePersonaViews(roles)` (the persona roles the user holds, plus
  `coach` when they can supervise).
- `usePersonaAuth(requiredRole, { alsoAllow })`: the coach layout calls
  `usePersonaAuth("coach", { alsoAllow: ["admin", "owner"] })`. All other
  shells are unchanged.
- Coach layout shows a slim banner for supervisors: "Admin coverage — you
  can see every session in the academy and mark attendance for any of them."
- `PersonaSwitcher` lists `availablePersonaViews`, so an admin-only user now
  sees "Admin view / Coach view".
- Today, Sessions, and Session detail render a small "Coach: {name}" line
  when `coach_name` is present.
- `lib/api/coach.ts` types gain optional `coach_id` / `coach_name`.

Post-login landing is unchanged (`homeForRoles` still prefers admin).

## Security notes

- Supervisor status is derived only from academy-scoped `claims.roles`;
  `platform_admin` does not get coach access through this path.
- All reads stay behind the tenant-scoped repositories; the widened queries
  add no cross-tenant path.
- `docs/security-matrix.md` gets a note under Conventions: the coach BFF is
  a *surface*, and the Admin column's "Yes" cells for attendance / coaching
  are now exercised through it. The wrong-persona rule (404 for parent and
  student) is unchanged.

## Testing

Backend (`backend/v2/tests/interface/test_coach_admin_coverage.py`):

- admin `GET /coach/today` returns every non-cancelled occurrence on the
  date, including `s-other-coach`, each with `coach_name`.
- admin `GET /coach/sessions` returns academy-wide upcoming occurrences.
- admin `POST /coach/attendance` on `occ-other-coach` → 200; `marked_by` is
  the admin.
- admin bulk mark on `occ-other-coach` → 200.
- admin `PATCH` correction on a mark older than 48h → 200 (admin path).
- admin `GET /coach/sessions/{s-other-coach}/roster` → 200.
- coach on `occ-other-coach` still 409 `SessionNotAssigned`; parent still
  404 on every route above.
- Existing `*_admin_persona_returns_404` tests are inverted to assert the
  new behaviour; the golden-master baseline is regenerated for the two new
  nullable fields and the diff is reviewed in the PR.

Frontend: `lib/api/me.node-test.mjs` covers `canSuperviseCoaching` and
`availablePersonaViews`. Existing e2e coach specs keep working because the
coach fixture still holds only the coach role.

## Rollout

Single PR. No migration, no new env var, no data change. Rollback is
reverting the PR: the guard change is additive and the widened queries are
only reached by supervisor claims.
