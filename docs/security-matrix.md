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

**Coach supervision (#632).** The coach BFF (`interfaces/coach/`) is a *surface*, not a role: it admits `coach` **and** the academy-scoped supervisor roles `admin` / `owner` via `require_coach_surface()`. A supervisor on that surface sees every session in the academy and passes every "assigned to session" check (`CoachAssignedSessionLookup`), so the Admin column's "Yes" cells for attendance and coaching are exercised through the coach routes. Writes stay attributed to the supervisor's own user id; attendance corrections take the admin path (no 48h window). Parents and students still get 404 on every coach route, and platform roles never grant coach-surface access. Design: `docs/superpowers/specs/2026-09-02-admin-coach-coverage-design.md`.

**Staff money tiers (#553).** Academy roles `billing` and `front_desk` are standalone staff tiers (owner decision 2026-09-22); neither implies `admin`. The predicates live in `backend/v2/shared/auth/staff_tiers.py`. `billing` sees family money amounts and records payments a family already made: `POST /admin/billing/invoices/{id}/record-payment` and `POST /admin/payments/{id}/mark-paid` are guarded by `require_staff_tier("billing")` (owner, admin or billing; `interfaces/admin/staff_tier.py`, route set `STAFF_TIER_ROUTE_PATHS`). `front_desk` sees an "owes money" flag only and has no money write. The People CRM family index reads (`GET /admin/families`, `/admin/families/summary`, `/admin/families/{family_id}/record`) are `require_staff_tier("front_desk")` (owner, admin, billing or front desk; L2b): the server serializes money per caller with `money_visibility.family_money_view`, so owner, admin and billing get amounts and front desk gets `money: null` plus the `owes_money` boolean, never an amount (`tests/interface/test_admin_family_index_staff_tiers.py` walks the raw payload). The balance sort and Overdue filter never apply for front desk. Every other CRM route, the family Billing tab and the money reports stay closed to front desk. Every money-moving route (refund, void, discount, undo-paid, adjustments, fees, card charges) stays `require_owner`. Every other admin route stays `require_persona("admin")`, so a bare `billing` or `front_desk` member gets 404 there. Existing `admin` memberships keep the money capabilities they had (admin is in the billing tier). Granting or revoking `billing`/`front_desk` is owner-only, like `admin`/`owner`. Enforced by `tests/structural/test_money_route_staff_tiers.py` and `tests/interface/test_admin_staff_tier_money_routes.py`. The Staff page (`/admin/users/{id}`) offers the staff tiers to owners only. The academy always keeps one live owner: removing the role, replacing every role or disabling the account of the last active owner membership is refused with 409 `Identity.CannotRemoveLastOwner` (`MongoUserRepository._assert_not_last_owner`; invited or suspended owners do not count). Every grant and revoke writes a `user.role_added`/`user.role_removed` audit row. Enforced by `tests/interface/test_staff_role_assignment.py` and `tests/contract/test_staff_role_assignment_real_mongo.py`.

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
