# Should Students move into Families? Recommendation for /admin/students, /admin/families and /admin/users

## Answer

**No, and there is a partial fix instead.** /admin/students should not move into /admin/families. The backend has no family record. A "family" is a parent user id, and the Families list is built by walking students and de-duplicating on `parent_id` (backend/v2/composition/admin.py:1874-1883). Students is the main collection and Families is a money view of it. Folding Students into Families would reverse that relationship, add a click to every child lookup, and leave students whose parent can't be resolved with no page. The duplicated look is real, but it comes from labels and overlapping lists rather than too many pages. The fix:

- Give each page one job: Students is for children, Families is for money, and Users becomes Staff.
- Link the pages to each other.
- Remove parents from the Users list.

This also follows the direction the 2026-09-12 audit chose (docs/reviews/2026-09-12-ui-persona-lifecycle-audit.md:236-246).

## What the three pages do today

| | Unique | Overlaps with |
|---|---|---|
| **Students** (WORK, screen-meta.ts:55) | Edits the profile, medical info and status with a reason. Hold, return, transfer, fee override, recurring discount, session-type move and price override. Change-parent. Past enrollments, attendance, waiver, pathway progress. | Families shows the same enrollment rows and a "Stop all classes" button. Both lists show a parent column and a dues/outstanding signal. |
| **Families** (MONEY, screen-meta.ts:73) | Family-wide autopay on/off, billing invite, invoice ledger (send, record payment, charge, void, refund, one-time discount, add charge, bill this month), timeline, Fix something panel. | Its parents are the same user_id as Users?role=parent, but neither page links to the other (users/[userId]/page.tsx has no /admin/families link). Its invite is a second endpoint (`/admin/billing/setup/{id}/invite` vs `/admin/users/{id}/login-invite`). |
| **Users** (WORK, screen-meta.ts:57) | Creates accounts, edits a parent's email, phone and status, manages roles, sends login invites, sets coach pay rates, assigns coaches to sessions. | The Parents pill (AdminUsersDirectory.tsx:26-31) and the /admin/parents redirect make this a third parent list. |

All three nav items use the same `user` icon.

## Recommended target design

- **/admin/students** (WORK, "Students", subtitle "Every child: classes, attendance, status")
  - Same list as today.
  - The Parent cell links to /admin/families/{parent_id}, and shows plain text when the parent is empty.
- **/admin/students/[studentId]**
  - Stays the one place to act on a child.
  - Reads `?tab=`. Today `useState("overview")` at page.tsx:59 ignores it, so the family page's "Recurring discount" link and the Progress tab strip (StudentDetailTabs.tsx:86) land on the Overview tab.
  - Reuse the existing `FamilyBillingLink` (FamilyBillingLink.tsx, already on the Billing tab) rather than adding a second family link.
- **/admin/families** (MONEY, "Families", subtitle "Parent accounts: balance, card, autopay, invoices")
  - Money only.
  - Its header gains an "Account & login" link to /admin/users/{parentId}.
  - Its StudentsPanel links to the child with `?tab=sessions`.
  - Optionally drop the duplicate per-child "Stop all classes" (StudentsPanel.tsx:142-147). The same control is on the student header (page.tsx:638).
- **/admin/users**, renamed **Staff** (subtitle "Coaches and admins: logins, roles, pay")
  - Pills: All staff, Coaches, Assistant coaches, Admins. The Parents pill is removed.
  - The detail page stays the account editor for any user id, parents included.
  - It adds a "Family billing" link when the user holds the parent role.
  - Coach panels are gated on the roles array instead of `user.role === "coach"` (page.tsx:76).
- **Redirects**
  - /admin/parents goes to /admin/families.
  - /admin/coaches and /admin/billing-setup stay as they are.
  - No page.tsx is added or deleted, so the tests that assert `routes == 92` still pass (test_inventory_acceptance_coverage.py:153, test_inventory_control_evidence.py:88).

**What disappears:**
- Parents as a list in Users.
- The shared icon and the vague subtitles.
- The dead invoice, payment and void dialogs in students/[studentId]/billing-dialogs.tsx (keep BillingDialogFrame, Actions and Error).
- The unused `createAdminStudentInvoice` in lib/api/v2/students.ts.
- The unused `fixedRole` prop.

**Corrections from the review of earlier drafts:**
- **Keep the Parent option in Add user** (AdminUsersDirectory.tsx:151,204). It is the only admin path that creates a parent. The change-parent picker (students/[studentId]/page.tsx:73-75) can only pick parents who already exist. The claim that "parents come in through registration" does not hold.
- **Parents with zero children are not on Families.** Families rows are built from students (admin.py:1876), so these parent accounts would otherwise vanish from every list.
- **The parent_id="" row.** The Families list already renders a dead row for students with an empty parent_id. Filter it out.

## Why not the alternatives

- **Students into Families:** this reverses the data model and is roughly XL work: about 6 e2e specs, the QA manifest, the progress-return helper used by 5 pages, and StudentDetailTabs. It also makes every child lookup take a detour through the parent.
- **One new People directory:** the audit's longer-term item 8. It is worth doing later, but it builds on /admin/students, not Families, and it is more than "easy".
- **Remove /admin/users/new and the Parent create option now:** owners would lose the only screen that creates admins, and admins would lose the only way to create a parent. The dialog would first need the owner-aware role list.

## Migration plan

1. **screen-meta.ts (S):** relabel Users to Staff, update the three subtitles, and give each nav item its own icon. Update screen-meta.test.ts:110-127 if the titles change. Staff still highlights on /admin/users/{parentId}, so accept that or tweak the breadcrumbs.
2. **AdminUsersDirectory.tsx (S-M):** drop the Parents pill and keep the Parent create option. The list payload `AdminUserView` (admin.ts:1266-1273) carries only the primary role, and `roles[]` lives on `AdminUserDetail`. So excluding parent-only users needs a backend `?exclude_role=parent` or `roles[]` in the list; a client-side filter would hide coaches whose primary role is parent. A `?role=parent` URL shows a banner that links to Families.
3. **parents/page.tsx (S):** redirect to /admin/families. Rewrite admin-shell.spec.ts:986-1002, which asserts the old `users?role=parent` target.
4. **Cross-links (S):**
   - FamilyHeader.tsx gets "Account & login".
   - users/[userId] gets "Family billing" when the user is a parent, plus the roles-based coach gating.
   - The Students Parent cell becomes a link.
5. **Student detail `?tab=` (S):** read `useSearchParams` with `parseStudentDetailTabId` (it already exists in StudentDetailTabs.tsx), and write the tab back with `router.replace`. This may need a Suspense boundary. Point the family "Recurring discount" link at `?tab=sessions`. Add an e2e check in tuition-discounts.spec.ts.
6. **Families list cleanup (S):** drop the `parent_id == ""` row.
7. **Dead-code sweep (S):** remove the unused code listed above.
8. **Tests (S):** run admin-shell, saas-launch-route-matrix, admin-students, admin-family-billing, tuition-discounts, screen-meta.test.ts and the backend inventory tests. Write a release note with the 3 required sections and the real PR number, and record in the audit doc that item 8 is partly delivered.

**Optional:**
- **"On hold" filter (M):** "held" is a per-enrollment state, not a student status (departure_policy.py:75-100), so the filter needs backend aggregation in `list_admin_students`, not a new query value.
- **"Live child" default filter on Families (M):** this is a backend change, and it shifts the numbers in the summary tiles.

Overall effort is S to M, with no route changes.

## Decisions for you

1. **Rename Users to Staff and take parents out of its list?** Parent account edits would then be reached through Families, then "Account & login", which is one extra click.
2. **Where do you create a parent by hand?** Either keep the "Parent" option in Staff's Add user, or add "Add family" on Families. Then decide how parents with no children stay findable: a Families "No children yet" view, or keeping them visible in Staff.
3. **Remove "Stop all classes" from the family page and hide departed families by default?** Both reduce duplication but change what admins see today.