# Parent Profile Completion — Implementation Plan

**Design:** `docs/superpowers/specs/2026-07-29-parent-profile-completion-design.md`
**Date:** 2026-07-29

Six slices. Each is independently shippable and leaves the suite green. Slices 1–3
deliver the parent-facing fix; 4 gives admins the backstop; 5 stops new gaps; 6 is
the rollout check.

---

## Slice 1 — Completeness rules (pure, no I/O)

**New:** `backend/v2/shared/profile/completeness.py`

Pure module, no context imports. Define:

- `PARENT_REQUIRED = ("first_name", "last_name", "phone", "email_confirmed")`
- `CHILD_REQUIRED = ("full_name", "date_of_birth", "emergency_contact_name",
  "emergency_contact_phone", "medical_notes")`
- `MEDICAL_NONE_SENTINEL = "__none_declared__"`
- `ParentFacts` / `ChildFacts` — frozen pydantic models of plain values
- `ProfileGaps` — `parent: list[str]`, `children: dict[str, list[str]]`,
  `is_complete: bool`
- `evaluate(parent: ParentFacts, children: Sequence[ChildFacts]) -> ProfileGaps`

Rules:
- A value that is `None`, `""`, or whitespace-only counts as missing.
- `medical_notes` is satisfied by the sentinel **or** by non-empty text.
- `email_confirmed` is satisfied by a non-null `email_confirmed_at`.
- Gap keys are stable strings; the frontend maps them to labels.

**Tests:** `backend/v2/tests/unit/test_profile_completeness.py` — table test over
combinations: all-present, each field individually absent, whitespace-only values,
medical sentinel, medical free text, zero children (parent gaps still reported).

**Verify:** `pytest backend/v2/tests/unit/test_profile_completeness.py` and
`lint-imports` (the module must import nothing from `contexts/`).

---

## Slice 2 — Backend: parent profile read + write

### 2a. Persona-neutral student write

`backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`

Rename the body of `update_admin_student` to `update_student_profile(student_id,
command)` and have `update_admin_student` delegate. Behaviour, diffing, and the
`_write_audit` call are unchanged — this is a pure extraction so parent code does
not import an admin-named symbol.

**Verify first:** run the existing admin student tests *before* touching anything
else in this slice, so a regression here is unambiguous.

### 2b. Email confirmation field

`backend/v2/contexts/identity/domain/models.py` — add
`email_confirmed_at: datetime | None = None` to `User`. Optional with a default,
so existing documents deserialize unchanged; no migration needed.

Add the read/write to `mongo_user_repo.py` alongside the existing `phone` handling.

### 2c. Views

`backend/v2/interfaces/parent/views.py`:

- `ParentProfileGapsView` — `parent: list[str]`, `children: dict[str, list[str]]`,
  `is_complete: bool`
- `ParentSelfChildView` — `student_id`, `full_name`, `date_of_birth`,
  `emergency_contact_name`, `emergency_contact_phone`, `medical_notes`,
  `no_medical_conditions: bool`
- `ParentSelfProfileResponse` — parent fields, `email`, `email_confirmed`,
  `children`, `gaps`
- `UpdateParentProfileRequest` — `model_config = ConfigDict(extra="forbid")`;
  `first_name`, `last_name`, `phone`
- `UpdateParentChildRequest` — `extra="forbid"`; the five child fields only.
  DOB validator: valid ISO date, not in the future, not more than 100 years ago.

`extra="forbid"` on both request models is what enforces the field allow-list —
do not omit it.

### 2d. Routes

**New:** `backend/v2/interfaces/parent/profile_routes.py`, modelled on
`backend/v2/interfaces/coach/profile_routes.py`:

- `GET  /profile`
- `PATCH /profile`
- `POST /profile/confirm-email`
- `PATCH /children/{student_id}`

All under `Depends(require_persona("parent"))`. Register in
`backend/v2/interfaces/parent/router.py`; add the callables to
`backend/v2/interfaces/parent/deps.py` following the existing `ParentUseCases`
shape.

### 2e. Composition

`backend/v2/composition/parent.py`:

- `get_parent_profile(user_id)` — read the identity user and the parent's
  students, build `ParentFacts` / `ChildFacts`, call `evaluate`, return the view.
- `update_parent_profile(user_id, request)`
- `confirm_parent_email(user_id)`
- `update_parent_child(user_id, student_id, request)` — **ownership gate first**:
  load the student in the request tenant; not found → 404; `parent_id !=
  user_id` → 403. Then map to the student-profile command with
  `actor_id=user_id`, `reason="parent self-service profile update"`, and call
  `update_student_profile`.

The `no_medical_conditions` flag maps to the sentinel on write and back to a
boolean on read; it is never stored as a separate field.

**Tests:** `backend/v2/tests/interface/test_parent_profile_routes.py`
- GET returns gaps matching the seeded fixture
- PATCH updates parent phone; gaps shrink accordingly
- PATCH another parent's child → 403
- PATCH a child in another academy → 404 (assert **not** 403)
- PATCH with `status` or `parent_id` in the body → 422
- PATCH with a future DOB → 422
- a parent write produces an audit record with actor = parent user id
- confirm-email stamps the timestamp and clears the `email_confirmed` gap

**Verify:** `pytest backend/v2/tests/interface/test_parent_profile_routes.py`
plus the existing admin student tests, `mypy`, and `lint-imports`.

---

## Slice 3 — Frontend: profile page + banner

### 3a. API client

`frontend/lib/api/parent.ts` — `getParentProfile`, `updateParentProfile`,
`confirmParentEmail`, `updateParentChild`, matching the existing helpers' style.

### 3b. Profile page

**New:** `frontend/app/(parent)/parent/profile/page.tsx`

- "About you" section: first name, last name, phone, and the email row with
  **"Yes, that's right"** / **"That's not mine"**.
- One section per child: full name, DOB, emergency contact name + phone, medical
  notes with a **"No known conditions or allergies"** checkbox that disables and
  clears the text area.
- Missing fields visually marked; save per section, not one giant submit.

### 3c. Banner

`frontend/app/(parent)/layout.tsx` — fetch the profile once, render a banner when
`gaps.is_complete` is false. Copy names the child and count. Dismissal writes to
`sessionStorage`, so it returns on the next login.

### 3d. ⚠️ Route manifest — same commit

`docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` must gain an
entry for `/parent/profile` with a `source` pointing at the new page file.

**Verify:** `pytest backend/v2/tests/unit/test_audit_inventory_manifest.py
backend/v2/tests/unit/test_inventory_static_gaps.py
backend/v2/tests/unit/test_inventory_control_evidence.py` — all three read that
manifest. Then `pnpm build` and `pnpm lint` in `frontend/`.

---

## Slice 4 — Admin gap report

`backend/v2/interfaces/admin/directory_routes.py` — add an optional `missing`
query parameter (comma-separated keys) to the students list. Push the predicate
into the Mongo query in `mongo_student_repo.py` so cursor pagination stays
correct; do **not** filter in Python after paging, which would produce short
pages and a broken cursor.

`frontend/app/(admin)/admin/students/page.tsx` — a "Missing details" filter and a
count badge. Admins fill gaps through the existing detail form; no new write path.

**Tests:** filter returns exactly the incomplete students; pagination is correct
across a page boundary with the filter applied; an unknown `missing` key → 422.

---

## Slice 5 — Stop new gaps at registration

### 5a. Domain + DTO

- `backend/v2/contexts/onboarding/domain/models.py` — `ChildProfile` gains
  `emergency_contact_name`, `emergency_contact_phone`, `medical_notes`, all
  defaulting to `""`.
- `ChildProfileView` in `backend/v2/interfaces/parent/views.py` — same fields,
  optional. **Keep them optional**: the wizard autosaves partial drafts via
  `PATCH`, and a required field here breaks every intermediate step.

### 5b. Checkout guard

`backend/v2/composition/parent.py:1363`,
`ParentComposition.start_checkout_for_application` — validate child DOB, parent
phone, and emergency contact **before the paid/zero-amount branch**. The $0 path
skips Stripe and goes straight to `PENDING_APPROVAL`; a guard inside the paid
branch would let free registrations through incomplete.

Raise a typed error carrying the missing field keys; the route maps it to 422 and
the wizard sends the parent back to the right step.

### 5c. Carry-through on approval

`backend/v2/composition/admin_registration_review.py` — the mapping from
`app.child_profile` into the created student appears on both the approve and the
waitlist-promote paths (around lines 246, 375, 596, 604). Extend **both** to pass
the new fields.

### 5d. Wizard

`frontend/app/(parent)/parent/onboarding/page.tsx` — `ChildStep` gains emergency
contact name, phone, and the medical notes field with the "no known conditions"
checkbox.

**Tests:**
- checkout rejected when the application lacks DOB → 422 naming the field
- **checkout rejected on the $0 path too** — reuse the same-day-cutoff fixture
  from the existing zero-amount test
- emergency contact entered in the wizard appears on the student after approval
- and after waitlist promotion

**Verify:** `pytest backend/v2/tests/unit/test_parent_composition.py
backend/v2/tests/interface/test_parent_sessions_checkout.py
backend/v2/tests/application/`.

---

## Slice 6 — Rollout

1. Full suite, `mypy`, `lint-imports`, `pnpm build`.
2. Release note with the three required sections and the real PR number — CI
   gates on this.
3. After deploy, open the admin gap report and record the baseline count of
   incomplete students. That number is the measure of whether the banner works;
   re-check in two weeks.
4. If the count barely moves, the follow-up is an email nudge (deliberately out
   of scope here) or promoting the banner to a gate on checkout for **existing**
   families — a decision to make with the data, not now.

---

## Risks

| Risk | Mitigation |
|---|---|
| First parent write path in the codebase — auth mistakes are tenant-crossing | Ownership check before any write; explicit 403-vs-404 tests; run the security-reviewer agent on the diff |
| Parent overwrites an admin's medical note | Full audit trail with parent as actor; admins see the change in history |
| Route manifest audit breaks CI | Manifest entry in the same commit as the route; three named tests to run |
| `extra="forbid"` omitted, letting a parent set `status` | Explicit 422 test for that exact payload |
| Checkout guard placed inside the paid branch | Explicit $0-path test; called out in the slice |
| Wizard autosave breaks if new fields are made required on the DTO | Fields stay optional; enforcement only at checkout |

## Out of scope

T-shirt size, previous experience, skill level; email and WhatsApp nudges; any
hard gate for existing families; parent-editable login email; franchise rollup.
