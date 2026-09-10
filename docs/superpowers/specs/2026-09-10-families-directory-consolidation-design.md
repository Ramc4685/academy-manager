# Families directory consolidation — design

Date: 2026-09-10. Owner decisions from the brainstorming session are recorded inline.
Second of four specs from the 2026-09-10 admin-UX session.

## 1. Purpose

Two admin surfaces show the same parent: `/admin/users?role=parent` (the Users directory
— name, email, phone, role, status, login-invite actions) and `/admin/families` (the
Family billing page from spec `2026-09-05-family-billing-design.md` — registration state,
card, autopay, balance, kids, invoices, timeline). An admin looking for "the Sharma
family" has to know which one has what.

There is no `Family` model. A family is one parent `User` plus the `Student` rows whose
`parent_id` points at it. That stays true. This spec makes `/admin/families` the one
place for parents by folding the identity columns and login actions into it, and removes
parents from the Users directory.

## 2. Owner decisions

| Question | Decision |
|---|---|
| Parents in the Users directory | Removed. `/admin/users` keeps Coaches and Admins. `/admin/parents` and `/admin/users?role=parent` redirect to `/admin/families`. |
| New data model | None. 1 parent user = 1 family. Shared custody / second guardian is a known gap, deferred until a customer asks (a `co_guardians` list would slot into the header without restructuring). |
| Detail page identity | Folded into `FamilyHeader`, not a new panel. |
| Creating a parent | The "Add parent" dialog moves from the Users directory to the Families list. |

## 3. Families list

Replaces both lists. One row per parent user in the tenant.

Columns: Family (parent name, kids' first names underneath) · Contact (email, phone) ·
Login (never invited / invited on date / active) · Billing (registration chip: registered
/ no card / not invited) · Autopay · Outstanding · row actions (Open, Send invite when
applicable).

Search box on name, email, phone and child name (server-side; the existing families
read model already joins students). Filters: login state, billing state, "has balance".
Default sort: name; a one-click "Needs attention" sort puts outstanding-balance and
never-invited rows first.

Backend: the families list endpoint gains `q`, `login_state` and pagination matching the
Users directory's cursor pattern; the login-invite facts come from the `users` document
already read (`login_invite_sent_at`, `has_login_account`). Wiring lives in
`composition/families.py` (created by the family billing spec), not `composition/admin.py`.

## 4. Family detail page

`FamilyHeader` becomes the identity-and-status strip: name, email (mailto), phone (tel),
login badge, kids count, registration chip, and the actions the user detail page had for
a parent — **Send / resend invite**, **Send password reset**, **Edit contact details**
(name, phone; email edit stays the existing admin-only path with its warning). Roles are
not editable here: a parent who is also a coach is managed from the Users directory.

Everything below the header is unchanged: StudentsPanel, InvoicesPanel, TimelinePanel,
FixSomethingPanel. Each student row in StudentsPanel links to the student page (today it
is one-way).

## 5. Users directory

`AdminUsersDirectory` drops the Parents pill; `fixedRole="parent"` is removed. The user
detail page `/admin/users/[userId]` still opens for a parent when reached from an admin
membership or audit link, but its header shows "This is a parent — manage on the family
page" with a link, and its parent-specific panels (invite) are hidden there to keep one
write surface.

Nav: the "Users" item stays for coaches/admins; "Families" already exists.

## 6. What this unblocks

- Spec 4 removes the Student page's parent-identity fields and `ChangeParentPanel`
  (the parent picker moves to this page's StudentsPanel as "Move child to another
  family", reusing `POST /students/{id}/change-parent`).
- Spec 1 §2 noted the family page has no enrollment rows; a later slice can list each
  child's enrollments here and mount the same `DepartureActions` row.

## 7. Rollout

1. Families list + header changes ship first (additive; old pages untouched).
2. Verify parity: every parent visible in the Users directory appears in Families with
   the same email/phone/invite state (a one-off script compares the two endpoints).
3. Redirects + directory pill removal + Add-parent move in a second PR.

No migration. `/admin/parents` already redirects (UIC1, PR #324); only the target changes.

## 8. Out of scope

- Second guardian / shared custody.
- Merging duplicate parent accounts.
- Coach or admin directory changes beyond removing the Parents pill.

## 9. Testing

- Backend: list endpoint search on child name and email; login-state filter; tenant
  scoping (parent outside the tenant is absent, never 403).
- e2e: `/admin/parents` and `/admin/users?role=parent` land on `/admin/families`;
  invite from the family header updates the login badge; user detail for a parent shows
  the pointer and hides the invite panel; route-matrix and QA inventory manifest updated
  (a redirect target change touches `docs/qa/…inventory-manifest.json` — same commit).
