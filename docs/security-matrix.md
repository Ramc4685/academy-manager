# Security Matrix (Persona × Action)

**Status:** Authoritative. Referenced by [ADR-0005](adr/0005-clean-architecture-lite-monolith.md) and all `interfaces/<persona>/` routes.
**Ticket:** P0-07
**Last reviewed:** 2026-05-16

This matrix defines what each persona can do. **Every BFF route in `backend/v2/interfaces/<persona>/` asserts the relevant cell.** A persona that touches an action outside its column returns **404 Not Found** — never 403 — so the route's existence is not leaked.

Negative tests are mandatory: for every row, a test must assert that the *wrong* persona gets 404. Coverage is tracked at the bottom of this file.

## Conventions

- **Yes** — full access via the persona's BFF.
- **Self only** — access limited to the persona's own resource (e.g., a coach views their own payout, never another coach's).
- **Conditional: …** — access depends on a relationship (e.g., "own child", "assigned sessions").
- **No** — the action is not available to this persona; the BFF returns 404 for the path.

A request returning **404** means "the route does not exist for you," regardless of whether the resource exists.

## Matrix

| Action | Admin | Coach | Parent |
|---|:---:|:---:|:---:|
| **Sessions** | | | |
| View all sessions in academy | Yes | No | No |
| View sessions assigned to me | Yes | Yes | No |
| View sessions my child is enrolled in | Yes | No | Yes |
| Create session | Yes | No | No |
| Edit session | Yes | No | No |
| Cancel session | Yes | No | No |
| **Enrollment** | | | |
| Edit roster (add/remove student) | Yes | No | No |
| Confirm enrollment | Yes | No | Conditional: own child, via Stripe checkout |
| Transfer enrollment between sessions | Yes | No | No |
| Pause enrollment | Yes | No | Conditional: own child |
| Resume enrollment | Yes | No | Conditional: own child |
| **Waitlist** | | | |
| Join waitlist | Yes (on behalf) | No | Conditional: own child |
| View waitlist | Yes | No | Conditional: own child only |
| Promote from waitlist | Yes | No | No |
| Skip / remove from waitlist | Yes | No | No |
| **Attendance** | | | |
| Mark attendance for assigned session | Yes | Conditional: assigned to session | No |
| Edit historical attendance | Yes | No | No |
| View attendance for session | Yes | Conditional: assigned to session | Conditional: own child |
| **Coaching** | | | |
| Create lesson plan | Yes | Conditional: assigned sessions | No |
| Edit lesson plan | Yes | Conditional: own plans | No |
| View lesson plan | Yes | Conditional: assigned sessions | No |
| Create progress note for student | Yes | Conditional: assigned students | No |
| View progress notes | Yes | Conditional: assigned students | Conditional: own child |
| **Payments** | | | |
| View payment history (academy-wide) | Yes | No | No |
| View own payment history | N/A | N/A | Yes |
| Issue refund | Yes | No | No |
| Initiate checkout | N/A | N/A | Conditional: own child |
| Cancel subscription | Yes | No | Conditional: own subscription |
| **Finance** | | | |
| View academy revenue | Yes | No | No |
| View own coach payout | Yes | Self only | No |
| View coach payouts (any) | Yes | No | No |
| Record expense | Yes | No | No |
| **Identity** | | | |
| Invite user | Yes | No | No |
| Edit own profile | Yes | Yes | Yes |
| Reset own password | Yes | Yes | Yes |
| Change another user's role | Yes | No | No |
| Disable / enable account | Yes | No | No |
| **Comms** | | | |
| Send broadcast announcement | Yes | No | No |
| Send DM to coach | Yes | N/A | Yes |
| Send DM to parent | Yes | Yes (assigned children's parents) | N/A |
| View own messages | Yes | Yes | Yes |
| **Admin / System** | | | |
| View audit logs | Yes | No | No |
| Trigger waiver re-acknowledgement | Yes | No | No |
| Export academy data | Yes | No | No |

## Implementation Rules

1. **Persona path = persona scope.** A route under `interfaces/coach/` may only assert coach-column cells. A coach route attempting an admin action is a design error caught in code review.
2. **404, never 403.** Use FastAPI dependency: `def require_persona(persona: Literal["coach","admin","parent"])` that raises `HTTPException(404)` on mismatch.
3. **Conditional cells are enforced in the use case, not the route.** A coach calling `mark_attendance` for an unassigned session must be rejected by the `mark_attendance` use case (with a domain error `SessionNotAssigned`), not by an ad-hoc check in the route. This keeps authorization in the domain where it can be tested without HTTP.
4. **No persona escalation through the API.** A user with multiple roles (e.g., a parent who is also a coach) makes requests via the persona BFF appropriate to the action. The auth claim's `roles` field is checked against the persona path.
5. **Negative tests are mandatory.** Each row's "No" cells must have a test asserting 404 for that persona on the relevant route. Coverage is tracked below.

## Coverage Tracking

This section is updated per wave as routes ship.

### Wave 1A (Coach Today)

| Action | Coach has access | Wrong persona returns 404 | Test file |
|---|:---:|:---:|---|
| View sessions assigned to me | ✅ implemented | ☐ | `backend/v2/tests/interface/test_coach_today.py` |
| Mark attendance for assigned session | ✅ implemented | ☐ | `backend/v2/tests/interface/test_coach_attendance.py` |
| View attendance for session (coach: assigned) | ✅ implemented | ☐ | `backend/v2/tests/interface/test_coach_today.py` |

(Filled in as W1A-09 lands.)

### Wave 1B, 2, 3 — Not yet started

## Change Process

Adding or modifying a row requires:

1. PR updating this file.
2. PR adding the route or modifying the use case.
3. PR adding negative tests for the affected wrong-persona cells.

A row may not ship to production until all three are merged.
