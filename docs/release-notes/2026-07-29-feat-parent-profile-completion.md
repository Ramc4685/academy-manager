# feat-parent-profile-completion

PR: #383

## What changed
Adds a self-service way for parents to fill in missing student/parent
details, and stops new registrations from creating the same gap.

- New shared completeness rules (`backend/v2/shared/profile/completeness.py`)
  define what "complete" means for a parent and each child: parent
  `display_name`, `phone`, confirmed email; child `full_name`,
  `date_of_birth`, `emergency_contact_name`, `emergency_contact_phone`,
  `medical_notes` (a "no known conditions" checkbox counts as answered).
- First parent write path in the codebase: `GET/PATCH /api/v2/parent/profile`,
  `POST /parent/profile/confirm-email`, `PATCH /parent/children/{id}`. Every
  child write is ownership-checked against the tenant-scoped student list
  before anything is persisted, then routed through the existing audited
  `update_student_profile` with the parent stamped as actor. Login email is
  confirm-only, never editable, since it's the Firebase identifier.
- New `/parent/profile` page and a dismissible banner in the parent layout.
  Dismissal is session-scoped (`sessionStorage`), so it returns on the next
  login. Nothing a parent does today is blocked by an incomplete profile.
- Admin gap report: `GET /api/v2/admin/students?missing=date_of_birth,...`
  reuses the same completeness rules to filter the existing student
  directory.
- Onboarding wizard's child step gains emergency contact + medical notes.
  `start_checkout_for_application` now rejects an incomplete application —
  checked *before* the zero-amount branch, since that path skips Stripe
  entirely and would otherwise let a free registration through incomplete.
  The wizard's fields are carried onto the created/matched student on both
  the approve and waitlist-promote paths.
- The wizard's parent step now marks Phone `required`, matching the checkout
  guard. It was optional, so a parent could complete every step and only be
  refused at the payment button — a registration that succeeds on `main`
  today. When the guard does fire (an application drafted before these fields
  existed), the error names the missing details in plain language and returns
  the parent to the step that owns them instead of stranding them on the
  review screen; the backend ships the field list in `DomainError.details`
  rather than only in the message string.
- Fixed a pre-existing bug found while building this: `MongoUserRepository
  ._to_domain` never read `phone` off the Mongo document, so `User.phone`
  was always `None` — including through the existing coach self-service
  profile, which has silently returned `phone: null` since it shipped.

## Deploy notes
No new environment variables or migrations. `email_confirmed_at` on `User`
and the three new fields on `Student`/`ChildProfile` are optional/defaulted,
so existing documents deserialize unchanged. The route-manifest audit
(`docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`) gained
an entry for `/parent/profile`; two hardcoded route-count assertions in
`backend/v2/tests/unit/` moved from 79 to 80 accordingly.

## Risk / rollback
Medium — this is the first parent write path in the codebase, so the main
risk surface is authorization. Every child write is ownership-checked; a
student belonging to another parent or another academy both return 404,
undistinguished, matching the existing `_verify_child_ownership` pattern
elsewhere in the parent BFF. `extra="forbid"` on both parent-facing request
DTOs enforces the field allow-list (a parent cannot set `status`,
`parent_id`, or any admin-only field).

The checkout guard reads only the application draft the parent fills in
during this session — never a stored `Student` or `User` — so no existing
family with an incomplete record can be blocked from registering by it. The
one way it could have blocked a currently-registerable family was the
optional-Phone mismatch above, now fixed. 2782/2782 backend tests passing;
`pnpm build`/`typecheck`/`lint`/`e2e` clean. Rollback = revert the single PR; no
data migration to reverse, since all new fields are additive and optional.

Two follow-ups were spawned from risks surfaced while building this, not
fixed in this PR (need new read wiring, out of scope here): admin
`EditRosterAdd` already nulls a student's DOB on every roster add and now
also nulls the three new fields; registration approval/waitlist-promote can
null an existing sibling-matched student's already-good data when approving
an old application with blank fields.
