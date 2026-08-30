# Parent Profile Completion — Design

**Date:** 2026-07-29
**Status:** Approved (design)
**Author:** RamC (with Claude)

## Problem

Student and parent records are incomplete. Registration never asked for most of
what the system can store, so fields that matter — child date of birth,
emergency contact, medical notes — are empty for a large share of existing
families, and there is no way for a parent to fix that themselves.

Three concrete findings from the current code:

1. **Date of birth is soft-required.** The onboarding wizard marks it `required`
   in HTML, but the server DTO (`ChildProfileView.date_of_birth`,
   `backend/v2/interfaces/parent/views.py:27`) defaults to `""` and only
   validates format when non-empty. `Student.date_of_birth`
   (`backend/v2/contexts/enrollment/domain/models.py:77`) is `str | None`.
   Any student created by an admin or an import can land with no DOB
   permanently.

2. **Safety fields are collected from nobody.** `AdminStudentDetail`
   (`backend/v2/contexts/enrollment/application/use_cases/admin_directory.py:93`)
   carries `emergency_contact_name`, `emergency_contact_phone`, `medical_notes`,
   `previous_experience`, `t_shirt_size`. None of them appear anywhere in the
   registration flow. They are writable only through the admin directory.

3. **Parents have no write path at all.** The parent BFF exposes reads only —
   `GET /children` returns `student_id`, `full_name`, `status`, and counts. There
   is no endpoint for a parent to edit their own details or their child's.
   Coaches already have `GET/PATCH /api/v2/coach/profile`
   (`backend/v2/interfaces/coach/profile_routes.py`); parents have no equivalent.

A fourth item is worth stating because it changes the fix: **parent email cannot
be missing.** `User.email` is a required `EmailStr` and doubles as the Firebase
login identifier. The real risk is a *stale or wrong* address, which is a
confirmation problem, not a backfill problem.

## Goal

Every active family ends up with child DOB, parent name and phone, an emergency
contact, and a medical-notes answer on file — filled by the parent where
possible and by an admin where not.

## Non-goals

- Any hard gate. Nothing a parent can do today gets blocked by an incomplete
  profile. Explicitly decided: no blocking on checkout, enrollment, self-service
  requests, or waiver signing for **existing** families.
- Email or WhatsApp reminder campaigns. In-app banner plus admin follow-up only.
- T-shirt size, previous experience, skill level. Storable, not required.
- Franchise / cross-academy rollup of the gap report.
- Letting a parent change their login email in v1 (see "Email" below).

## Required-field set

| Field | Owner | Storage today | Collected at registration today |
|---|---|---|---|
| Child full name | student | `students.full_name` | yes |
| Child date of birth | student | `students.date_of_birth` | yes, but not enforced server-side |
| Emergency contact name | student | `students.emergency_contact_name` | **no** |
| Emergency contact phone | student | `students.emergency_contact_phone` | **no** |
| Medical notes | student | `students.medical_notes` | **no** |
| Parent first / last name | parent | `users.display_name` | yes |
| Parent phone | parent | `users.phone` | yes, optional |
| Parent email confirmed | parent | new `email_confirmed_at` | n/a |

**Medical notes is answered-or-explicitly-none.** A free-text field alone can
never be marked complete, because empty is indistinguishable from "nothing to
declare". The form carries a "no known conditions or allergies" checkbox; ticking
it writes a sentinel that satisfies the rule. The gap closes on either the
checkbox or non-empty text.

## Architecture

### Completeness rules — one shared definition

The required set spans two bounded contexts: parent fields live in `identity`,
child fields in `enrollment`. Putting the rule in either context would force a
cross-context import and fail import-linter.

The rule lives in a pure module under `backend/v2/shared/` that imports no
context. It takes plain values and returns a result:

```
ProfileGaps:
    parent:   list[str]              # e.g. ["phone", "email_confirmed"]
    children: dict[str, list[str]]   # student_id -> ["date_of_birth", ...]
    is_complete: bool
```

Orchestration — reading the parent from `identity`, the students from
`enrollment`, and combining them — lives in the composition layer
(`backend/v2/composition/parent.py`), where cross-context wiring already
happens for checkout and enrollment.

### Parent self-service API

Mirrors the coach profile pattern, under `require_persona("parent")`:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v2/parent/profile` | Parent fields, children with editable fields, computed `gaps` |
| `PATCH` | `/api/v2/parent/profile` | Parent first/last name, phone |
| `POST` | `/api/v2/parent/profile/confirm-email` | Stamp `email_confirmed_at` |
| `PATCH` | `/api/v2/parent/children/{student_id}` | DOB, emergency contact, medical notes |

**Authorization is the main new risk surface** — this is the first parent write
path in the codebase. Every child write verifies `student.parent_id ==
claims.user_id` *and* that the student is in the request tenant. A student
belonging to another parent returns 403; a student in another academy returns
404 (never 403, which would confirm existence across tenants).

**Field allow-list.** The parent request DTO carries only the four editable child
fields. `status`, `parent_id`, `notes`, `level`, and `t_shirt_size` are not
accepted from a parent under any circumstance.

**Overwrite policy.** A parent may overwrite an admin-entered value on their own
child, including medical notes — they are the authority on their child's
medical facts, and a read-only field would leave stale information in place with
no correction path. The audit trail is what protects the admin's work.

### Audit

Student writes today go through `MongoStudentRepo.update_admin_student`, which
diffs the document and writes an audit record. Parent writes must produce the
same record so the admin history stays complete.

Rather than have parent code import an admin-named symbol, the write is
extracted into a persona-neutral `update_student_profile(student_id, command)`
on the repository, with `update_admin_student` delegating to it unchanged. Parent
writes call it with `actor_id` = the parent's user id and a fixed reason of
`"parent self-service profile update"`, so admin-facing history distinguishes
parent edits from admin edits by actor.

### Email — confirm, do not edit

`User.email` is the Firebase login identifier. A profile form that rewrites it
silently rewrites the parent's credentials, and the production Firebase
enumeration behaviour makes that path more fragile than it looks.

v1 shows the address with a **"Yes, that's right"** confirmation that stamps
`email_confirmed_at`, and a **"that's not mine"** action that flags the record
for admin attention rather than changing anything. An unconfirmed address counts
as a parent gap. Changing the address stays an admin action.

### Banner and profile page

- New route `frontend/app/(parent)/parent/profile/page.tsx` — the form, grouped
  as "About you" and one section per child.
- Banner rendered from `frontend/app/(parent)/layout.tsx`, driven by the `gaps`
  payload. Copy names the child and the count:
  *"2 details missing for Aanya — add them"*.
- Dismissal is session-scoped (`sessionStorage`), so the banner returns on the
  next login. This is what makes "whenever the parent comes in next time" work
  without a hard gate.

⚠️ Adding an `app/` route trips the frontend route-tree audit.
`backend/v2/tests/unit/test_audit_inventory_manifest.py::test_inventory_manifest_matches_frontend_app_route_tree`
requires `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` to
list the new route, with a `source` pointing at a file that exists. The
`len(routes) >= 49` assertion is a floor and needs no change. The manifest entry
must land in the same commit as the route.

### Admin gap report

A `missing` filter on the existing admin students list rather than a new
endpoint — it reuses the cursor pagination and the detail form admins already
use to fill gaps:

```
GET /api/v2/admin/students?missing=date_of_birth,emergency_contact,medical_notes
```

Frontend adds a "Missing details" filter to `/admin/students` and a count badge,
so the incomplete set is one click from the roster. Admins fill gaps through the
existing detail form; no new admin write path.

### Stopping new gaps

A guard in `ParentComposition.start_checkout_for_application`
(`backend/v2/composition/parent.py:1363`) rejects an application missing child
DOB, parent phone, or emergency contact, with a typed error the wizard maps back
to the step that needs attention.

**The guard sits before the paid/zero-amount branch.** The $0 path skips Stripe
entirely and transitions straight to `PENDING_APPROVAL`; a guard placed inside
the paid branch would let free registrations through incomplete.

Supporting changes:

- `ChildProfile` (`backend/v2/contexts/onboarding/domain/models.py:44`) gains
  `emergency_contact_name`, `emergency_contact_phone`, `medical_notes`.
- `ChildProfileView` gains the same fields; they stay optional on the DTO so the
  wizard's autosave-per-step `PATCH` of partial drafts keeps working. Enforcement
  is at checkout, not on the DTO.
- The wizard's child step gains the emergency-contact and medical fields.
- `backend/v2/composition/admin_registration_review.py` — which already maps
  `child_profile` into the created student on approval — extends its mapping to
  carry them through. Both the approve and the waitlist-promote paths map the
  child profile; both need the new fields.

## Data flow

```
parent login
  → parent layout GET /api/v2/parent/profile
      → composition reads identity user + enrollment students
      → shared rule module computes ProfileGaps
  → gaps non-empty → banner (dismissible for the session)
  → /parent/profile form
      → PATCH profile        → identity user write
      → PATCH children/{id}  → ownership check → update_student_profile → audit
  → gaps recomputed → banner clears
```

## Error handling

| Case | Response |
|---|---|
| Child belongs to another parent | 403 |
| Child in another academy | 404 |
| Non-editable field submitted | 422 (DTO rejects unknown fields) |
| Malformed DOB, or DOB in the future | 422 with the field named |
| Checkout with an incomplete application | 422, body names the missing fields |
| Parent record missing | 404, matching the coach profile behaviour |

DOB gets a sanity range — not in the future, and not implying an age over 100 —
because a mistyped year is otherwise silently accepted and pollutes any
age-based grouping later.

## Testing

- **Rules:** table test over gap combinations, including medical-notes
  answered-as-none, and whitespace-only values treated as absent.
- **Ownership:** a parent cannot read or write another parent's child (403);
  cross-academy returns 404, not 403.
- **Allow-list:** submitting `status` or `parent_id` on the parent DTO is
  rejected.
- **Audit:** a parent write produces an audit record whose actor is the parent
  and whose changed-field list matches the diff.
- **Checkout guard:** an incomplete application is rejected on both the paid and
  the $0 path.
- **Registration carry-through:** emergency contact entered in the wizard appears
  on the student record after approval, and after waitlist promotion.
- **Manifest:** route-tree audit passes with the new `/parent/profile` route.

## Open items

None blocking. The email-editing decision is deliberately deferred: if stale
addresses turn out to be common in the gap report, revisit with a re-auth flow.
