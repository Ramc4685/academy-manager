# Admin sidebar regroup and rename, plus the attendance-date fix

> **Status: implemented. Kept as the design record.** Written 2026-09-20 as an implementation spec. The three open decisions in this document were made by the owner on 2026-09-22: the label stays "Students", Staff sits inside the PEOPLE group (six groups, not seven), and Families stays in PEOPLE. Everything below shipped as: PR 0 attendance-date fix #911; PR 1 six groups with stable nav ids #919; PR 2 `exclude_role` and `roles[]` on `GET /api/v2/admin/users` #918; PR 3 Users becomes Staff and `/admin/parents` redirects to `/admin/families` #921; PR 4 deep links and roles-aware coach panels #917. Where the "before" state or line numbers below differ from the code, the code wins.

Original status: implementation spec, no code changed. Written 2026-09-20.
Every citation was checked against `origin/main` at `5e3b8209f` (#834). Line numbers in the older memo, engineering spec and audit have drifted; use the ones here.

## 0. Summary

The rearrangement is a navigation change. No `page.tsx` is added or deleted, every URL keeps working, and the coach and parent apps are not touched.

- The sidebar goes from three groups (WORK, MONEY, COMMS · OPS) to six: TODAY, CLASSES, PEOPLE, REACH, MONEY, ACADEMY.
- "Users" becomes "Staff" and stops listing parents. Families moves from MONEY to PEOPLE. Five items that share two icons get their own icons.
- Two tiny backend changes: an `exclude_role` filter on the users list, and the attendance-date fix, which ships first as its own PR.
- Five PRs, four of size S and one S–M. Each can be reverted on its own.

## 1. What the code says that the brief did not

Where the code and the brief disagree, this spec follows the code.

| # | Brief said | Code says | Consequence |
|---|---|---|---|
| 1 | Admissions and Requests are two nav items; merge them "if achievable without new routes" | Already merged. `/admin/inbox` shipped in #813 (issue #776). The nav has one "Inbox" item (`screen-meta.ts:58`). `/admin/registrations` and `/admin/requests` are redirect stubs into `/admin/inbox?tab=…`. The Inbox page already shows a pending count on every tab from `GET /admin/inbox/counts`. | Nothing to build. TODAY is Dashboard plus Inbox. This is no longer an owner decision. |
| 2 | Classes group contains "Waitlist" | There is no Waitlist nav item. `/admin/waitlist/page.tsx` is a four-line redirect to `/admin/inbox?tab=waitlist`; the waitlist is an Inbox queue. | Do not add a Waitlist nav item. It would point at a redirect, highlight the wrong row after landing (the match runs on pathname), and split one queue across two groups. Link to the waitlist tab from the Sessions page instead (§3). |
| 3 | Exclude "deleted" marks (`is_deleted`) | v2 attendance has no `is_deleted`. An annulled mark is `status: "voided"` (#554, `coaching/domain/models.py:13-21`). `is_deleted` exists only on legacy v1 rows; `_recent_attendance` still filters it (`mongo_student_repo.py:1543`). | The fix excludes both `voided` and `is_deleted: true`. |
| 4 | — | `_attendance_summaries` was missed by #554. Voided marks count in the rate's denominator and can set `last_seen_at`. The reports read model already excludes them (`admin_reports_read_model.py:50-54`). | The attendance PR also closes this gap. |
| 5 | — | `last_seen_at` is `$max` of `marked_at` over every status, so an **absent** mark counts as "seen". A child marked absent three weeks running looks recently seen and is never `at_risk`. | The at-risk tile will go **up** after the fix. This is the correct number, but admins will notice. |
| 6 | Engineering spec §2: "Families becomes People" | The brief for this work says Students is the directory and the family page is the record. The memo shows why: Families rows are derived from students, not the reverse. | Follow the brief and the memo. Families is not renamed "People". |
| 7 | — | Nav testids are built from the label: `admin-nav-${slug(item.label)}` (`layout.tsx:276,311`). A rename silently changes the testid. | Add a stable `id` to each nav item (§2.3). Today only six owner-only testids are used by e2e and none of those labels change. |
| 8 | — | `composition/admin.py` is 4,480 lines against a 4,500 budget (`test_composition_is_wiring.py:27`). | Nothing in this spec adds a line there. |
| 9 | — | `DESIGN.md:302` names the three current groups. | Update that sentence in the sidebar PR. `DESIGN.md` and `PRODUCT.md` are untracked in the main checkout, so this is a manual edit there, not part of the PR diff. |

## 2. Before and after sidebar

### 2.1 Groups

Six groups, not the seven proposed. The brief had STAFF as its own group holding one item. At 16 rows plus seven captions the sidebar scrolls on a 768px-tall laptop and in the phone drawer, and admins use a phone about half the time (PRODUCT.md). Staff sits under PEOPLE instead. This is open decision 2.

The last group is named ACADEMY rather than SETTINGS, because Waivers is a working list, not a setting.

### 2.2 Every nav item

Current values are from `screen-meta.ts:49-93` (nav) and `:172-197` (titles and subtitles). "—" means unchanged.

| # | Route | Now: group / label / icon | New group | New label | New icon | New subtitle | ownerOnly | User problem fixed |
|---|---|---|---|---|---|---|---|---|
| 1 | `/admin` | WORK / Dashboard / home | TODAY | — | — | — | no | Group only. The daily start point and the work queue sit together at the top. |
| 2 | `/admin/inbox` | WORK / Inbox / check | TODAY | — | — | — | no | Inbox was sixth in WORK, below Users. It is the second thing an admin opens each day. |
| 3 | `/admin/sessions` | WORK / Sessions / calendar | CLASSES | — | — | — | no | Group only. |
| 4 | `/admin/pathway` | WORK / Pathway / trophy | CLASSES | — | — | — | no | Group only. Pathway was between Students and Users, which are about people, not curriculum. |
| 5 | `/admin/students` | WORK / Students / user | PEOPLE | **Students** (recommended; decision 1) | — (`user`) | "Every child: classes, attendance, status" | no | "Roster and enrollment" does not tell it apart from Sessions, which also has rosters. |
| 6 | `/admin/families` | MONEY / Families / user | **PEOPLE** | — | **`users`** (new) | "Each family: children, balance, card, autopay" | no | Once parents leave the Users list, Families is the only list of parents. Nobody looks for a parent under MONEY. Its record page already holds children, a message link and a timeline, not only money. Same icon as Students and Users today. |
| 7 | `/admin/users` | WORK / Users / user | PEOPLE | **Staff** | **`badge`** (new) | "Coaches and admins: logins, roles, pay" | no | Three lists of parents today (Users' Parents pill, Families, the Students parent column). "Users" says nothing about who is in it. |
| 8 | `/admin/messages` | COMMS · OPS / Messages / msg | REACH | — | — | "Broadcasts, direct messages, email campaigns" | no | The email campaign composer exists but is the third lane at the bottom of the page (`messages/page.tsx:183`) and the subtitle "Inbox and broadcasts" never mentions it. "Inbox" in that subtitle also collides with the Inbox nav item. |
| 9 | `/admin/payments` | MONEY / Payments / pay | MONEY | — | — | — | no | unchanged |
| 10 | `/admin/reports` | MONEY / Month close / chart | MONEY | — | — | — | yes | unchanged |
| 11 | `/admin/expenses` | MONEY / Expenses / card | MONEY | — | — | — | no | unchanged (moves up one row because Families left) |
| 12 | `/admin/payouts` | MONEY / Coach payouts / whistle | MONEY | — | — | — | yes | unchanged |
| 13 | `/admin/billing-health` | MONEY / Billing Health / signal | MONEY | — | — | — | yes | unchanged. Order stays Payments, Month close, Billing Health, Expenses, Coach payouts; the existing comment at `:65-66` explains that order and no one has reported a problem with it. |
| 14 | `/admin/waivers` | COMMS · OPS / Waivers / check | ACADEMY | — | **`attend`** (exists, unused) | — | no | Same icon as Inbox today. Group renamed only because Messages left it. |
| 15 | `/admin/settings` | COMMS · OPS / Settings / cog | ACADEMY | — | — | — | no | Group only. |
| 16 | `/admin/audit-logs` | COMMS · OPS / Audit logs / filter | ACADEMY | — | — | — | yes | Group only. |

Where the Families money view lives: the same two URLs. `/admin/families` is the list and `/admin/families/[parentId]` is the record. From MONEY, the path to a family's money is unchanged in practice, because Payments rows already open the family record. Nothing else moves.

Breadcrumbs that change in `SCREEN_META`:

- `/admin/families`: `["Admin","Money","Families"]` becomes `["Admin","People","Families"]`.
- `/admin/families/[parentId]`: title "Family billing" becomes "Family"; breadcrumbs become `["Admin","People","Families","Family"]`. The subtitle is unchanged.
- `/admin/users`: title "Staff", breadcrumbs `["Admin","People","Staff"]`.
- `/admin/students`: `["Admin","People","Students"]`.
- `/admin/messages`: `["Admin","Reach","Messages"]`.
- `/admin/waivers`: `["Admin","Academy","Waivers"]` (today it says "Comms").

### 2.3 Supporting changes in the nav code

- `AdminNavItem` gains `id: string` (for example `"users"` stays the id of the Staff item). `layout.tsx:276` uses `item.id` for the testid. Existing testids keep their current values, so `admin-nav-month-close`, `admin-nav-coach-payouts`, `admin-nav-audit-logs`, `admin-nav-billing-health`, `admin-nav-payments` and `admin-nav-expenses` (`admin-shell.spec.ts:784-854`) do not change.
- `AdminNavIconKey` gains `"users" | "badge" | "attend"`. `frontend/components/ds/icons.tsx` gains two stroke factories, `users` and `badge`. `attend` is already there (`icons.tsx:114`). `renderNavIcon` falls back to `home` for an unknown key, so a typo shows a house icon rather than crashing; the unit test should assert that every nav icon key exists on `Icon`.
- The comment block at `screen-meta.ts:44-48` and the MONEY ordering comment are rewritten to match.
- `OWNER_ONLY_ROUTE_PREFIXES` and `navForRoles` are unchanged. With six groups, a non-owner still sees all six (every group keeps one non-owner item).

## 3. Redirects and cross-links

### 3.1 Redirects

| Change | File | Note |
|---|---|---|
| `/admin/parents` goes to `/admin/families` instead of `/admin/users?role=parent` | `frontend/next.config.ts:69` | Set `permanent: false` on this entry. The old 308 is why this move is awkward; a 307 costs nothing and is not cached. |
| Same destination in the fallback | `frontend/app/(admin)/admin/parents/page.tsx:14` and its doc comment | The file stays so the route manifest still matches. |
| `/admin/coaches` | — | Unchanged. It still lands on `/admin/users?role=coach`, which is still a valid Staff pill. |
| `/admin/billing-setup`, `/admin/dashboard`, `/admin/dues`, `/admin/reports/dues` | — | Unchanged. |

**Browsers that cached the old 308.** They will keep going to `/admin/users?role=parent` and nothing server-side can clear that. So that URL must stay a good landing: when `role=parent` is in the query, the Staff page still lists parents (it does not send `exclude_role`) and shows a banner: "Parents now live in Families" with a link to `/admin/families`. No pill is selected. This same URL is how parents with no children stay findable (§3.3).

No redirect is added through a layout or page `redirect()`. All new forwarding goes in `RETIRED_ROUTE_REDIRECTS` (#689, #827).

### 3.2 Cross-links

| Link | File | Detail |
|---|---|---|
| Students list: Parent cell opens the family record | `students/page.tsx:304` | `Link` to `/admin/families/{parent_id}`. Plain text when `parent_id` is empty. |
| Family record header: "Account & login" | `families/[parentId]/FamilyHeader.tsx` (next to the Message link at `:63-68`) | To `/admin/users/{parent_id}`. |
| User detail: "Family" link when the user holds the parent role | `users/[userId]/page.tsx` | To `/admin/families/{user_id}`. Check `roles.includes("parent")`, not `role`. There is no family link in this file today. |
| User detail: coach panels gated on roles | `users/[userId]/page.tsx:76` | `const isCoach = user.role === "coach"` becomes a check on `user.roles` for `coach` or `assistant_coach`. Today a coach whose first role is parent sees no pay-rate panel. |
| Staff page: links to coach pay and session assignment | `AdminUsersDirectory.tsx` | A line under the pills: "Pay rates and session assignment are on each coach's page. Payout runs are in Coach payouts." The second link is rendered only for owners, because `/admin/payouts` is owner-only. No new UI; both features already live on `users/[userId]`. |
| Staff page: "Parent accounts" | `AdminUsersDirectory.tsx` | Small text link to `/admin/users?role=parent`. Same link at the foot of `/admin/families`: "Looking for a parent with no children yet? Parent accounts". |
| Student detail reads and writes `?tab=` | `students/[studentId]/page.tsx:61` | Initialise from `useSearchParams` through `parseStudentDetailTabId` (`StudentDetailTabs.tsx:26-30`), write back with `router.replace`. May need a Suspense boundary. `StudentDetailTabs.tsx:86` already builds `?tab=` links that are ignored today. |
| Family record: "Recurring discount" lands on the right tab | `families/[parentId]/StudentsPanel.tsx:24,129-136` | `studentHref` gains an optional tab; the discount link passes the tab that hosts recurring discounts. Confirm the tab id in `SessionsPanel.tsx` before coding; the memo says `sessions`. |
| Sessions page: "Waitlist" link | `sessions/page.tsx` header actions | To `/admin/inbox?tab=waitlist`. This replaces the proposed Waitlist nav item. |
| Messages page: jump links to the three lanes | `messages/page.tsx:82,183` | Give each `LaneHeader` section an `id` (`broadcast`, `direct`, `campaign`) and add a row of three anchor links at the top. `/admin/messages#campaign` becomes a linkable entry point. No route, no tab state. |
| `FamilyBillingLink` | — | Unchanged. It already links the student Billing tab to the family record. |

### 3.3 Parents with no children

`list_parents` builds Families from students (`composition/admin.py:1984-1993`), so a parent account with no child is on no list once the Parents pill goes. The memo flagged this. The fix above costs no backend work: the "Parent accounts" link opens the existing `?role=parent` list. "Add user" keeps its Parent option (`AdminUsersDirectory.tsx:~231`), because it is the only admin path that creates a parent. After creating a parent from the Staff page, the success message links to the new account, since the new row will not appear in the Staff list.

## 4. Backend changes

### 4.1 `GET /api/v2/admin/users`: `exclude_role` and `roles[]`

Why: the list payload carries only the primary role, which is `roles[0]` (`mongo_user_repo.py:275-277`). Hiding parents in the browser would hide a coach whose first role is parent.

| File | Change |
|---|---|
| `backend/v2/interfaces/admin/directory_routes.py:80-89` | New query param `exclude_role: Literal["parent"] \| None = None`. Kept to the one value that has a use. Passed to the use case. |
| `backend/v2/contexts/identity/application/use_cases/admin_directory.py:118-127` | `ListAdminUsers.execute(role, *, academy_id, exclude_role=None)`. |
| `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py:326-333` | `list_users(..., exclude_role=None)`. Semantics: drop a user only when they hold **no role other than** the excluded one. A parent who is also a coach stays. Shape: keep docs where `roles` has an element not equal to `parent`, or where `roles` is missing and legacy `role` is set and not `parent`. A doc with no roles at all is treated as parent (that is what `_to_admin_summary` does) and is dropped. Combine with the academy filter and any `role` filter under `$and`. |
| `AdminUserSummary` and `backend/v2/interfaces/admin/views.py:25-30` (`AdminUserView`) | Add `roles: list[...] = []` to the list payload. Additive. Lets a Staff row show "Coach · Parent". |
| `frontend/lib/api/admin.ts:1311-1318,1560-1563` | `AdminUserView.roles?`, and `listAdminUsers(role?, opts?: { excludeRole?: "parent" })`. If the generated client under `frontend/lib/api/generated/` carries this type, regenerate it; do not hand-edit. |
| `backend/v2/composition/admin.py` | **No change.** It only constructs `ListAdminUsers(users_r)`. |
| Audit inventory manifest | No change. The manifest lists routes, and no route is added. Re-run `test_audit_inventory_manifest.py` anyway. |

Tests: a contract test against real Mongo for the repo (parent-only dropped; coach+parent kept; legacy doc with `role` and no `roles`; doc with neither; `role=coach` combined with `exclude_role=parent`). An interface test for the param, including the 404 for a non-admin persona. Any fake user repo used by other tests must apply the same rule, not return everything.

### 4.2 Families list: the empty-parent row

Students with `parent_id == ""` collapse into one dead row. Fix it at the source with a net-zero edit in `composition/admin.py:1987`: `if student.parent_id and student.parent_id not in seen:`. One line changed, none added, so the budget is untouched. If the reviewer prefers not to touch that file at all, filter `parent_id === ""` in `families/page.tsx` instead. Pick one, not both.

### 4.3 Attendance-date fix

See §5. It is a separate PR and ships first.

## 5. Attendance-date fix (PR 0)

### 5.1 Today

`_attendance_summaries` (`mongo_student_repo.py:2116-2160`):

- Window: `marked_at >= now - 90 days`. That is when the coach tapped, not when the class was.
- `last_seen_at = $max(marked_at)` over all statuses, including absent and voided.
- Rate = present+late over every row, voided included.
- No join to `session_occurrences`.

`last_seen_at` feeds `derive_lifecycle` (`enrollment/domain/lifecycle.py:179-183`): a student is `at_risk` when `last_seen_at` is missing or older than the cutoff. The cutoff is the oldest of the last 3 non-cancelled occurrences of the class within 120 days (`_at_risk_cutoffs`, `:1969-2017`). The cutoff is a class date; `last_seen_at` is a tap time. They are compared directly today.

### 5.2 Target

- **Last attended** = the latest class date (`session_occurrences.start_at`) among the student's `present` or `late` marks. Lookback 120 days, to match `_AT_RISK_LOOKBACK_DAYS`.
- **Rate** = (present + late) / (present + late + absent) over classes whose `start_at` is in the last 30 days. `None` when the denominator is zero.
- Excluded everywhere: `status == "voided"`, `is_deleted == true`, and marks on cancelled occurrences.
- Field names in the DTOs (`last_seen_at`, `attendance_rate`) do not change, so no frontend change is required for PR 0.

### 5.3 How

Occurrences first, then marks. Both steps are index-backed and no new index or migration is needed.

1. One query on `session_occurrences`: `academy_id`, `status != "cancelled"`, `start_at` between `now - 120d` and `now`. Project `occurrence_id` and `start_at`. Uses `session_occurrence_status_calendar` (migration 0081). Normalise each `start_at` with `_as_utc`; Motor returns it naive.
2. One query on `attendance`: `academy_id`, `occurrence_id $in` those ids, `student_id $in` the page's students, `status $in [present, late, absent]`, `is_deleted != true`. Uses the prefix of `attendance_occurrence_unique`.
3. Fold in Python per student: max `start_at` over present/late gives last attended; rows whose `start_at` is within 30 days feed the rate.

Keep it batched. `test_list_admin_students_returns_rich_default_page_without_per_student_fanout` fails the build on any per-student query, and it should keep doing so.

Define the counted and present status tuples locally in the enrollment context with a comment pointing at #554. Do not import them from the billing context; that crosses a context boundary.

Rows with no `occurrence_id` (legacy v1) drop out of both numbers. Before deploy, count them in prod for the last 120 days. If the count is not zero, say so in the release note; do not add a fallback path for them.

Optional, same PR, separate commit: `_recent_attendance` (`:1531`) sorts by `marked_at` and labels rows with a `date` field that v2 never sets. Resolve the class date and session title through the same occurrence lookup. Additive fields only. Drop this commit if the PR grows past S.

### 5.4 Ripple

- The at-risk tile and `lifecycle_counts` on `/admin/students` will shift on deploy, mostly **up**: students with a run of absences stop looking "seen", and so do students whose old classes were marked late in a batch. Some will move the other way, where a mark was entered long after a recent class.
- The "last seen" date on the Students list changes from tap date to class date.
- The rate column changes for most students because the window shrinks from 90 to 30 days and voided marks drop out.
- Coach and parent apps: no effect. Neither `composition/coach.py`, `composition/parent.py` nor their interfaces read these fields. The `attendance_rate` on Month close is a separate calculation and is untouched. The `last_seen_at` string in `digests.py:984` is about logins.

### 5.5 Tests to add

In `backend/v2/tests/contract/test_admin_directory_mongo_student_repo.py` (real Mongo):

1. Naive and aware `start_at` on otherwise identical occurrences give the same `last_seen_at`, returned as aware UTC.
2. A mark made today for a class 40 days ago: last attended is the class date; the row is outside the 30-day rate.
3. Three straight absences with recent `marked_at`: `last_seen_at` stays at the older present mark and the student derives `at_risk`. This is the behaviour change; name the test for it.
4. A voided mark and an `is_deleted` mark change neither number.
5. A mark on a cancelled occurrence is ignored.
6. `lifecycle_counts["at_risk"]` for a seeded page, before-and-after style, so the tile shift is pinned.
7. The existing `test_active_student_who_stopped_showing_up_derives_at_risk` and `test_a_brand_new_class_never_calls_anyone_at_risk` still pass; update their seed data to include occurrences if they seeded marks only.

`test_enrollment_lifecycle.py` needs no change; `derive_lifecycle` is untouched. `FakeStudentDirectory` returns canned summaries and has no logic to keep in step.

## 6. Delivery plan

Order: PR 0, 1, 2, 3, 4. PR 1 and PR 4 do not depend on PR 2 or 3. Every PR needs a note in `docs/release-notes/YYYY-MM-DD-<slug>.md` with `PR: #<real number>` and the three exact headings `## What changed`, `## Deploy notes`, `## Risk / rollback` (`scripts/dev/release_notes_check.py:26`). Open the PR first to get the number, then add the note. `main` requires "CI Gate" and "Release Notes Gate"; no force-push, no amend.

Route count stays at 92 in every PR. No `page.tsx` or `route.ts` is added or deleted, so the manifest and the two count assertions (`test_inventory_acceptance_coverage.py:153`, `test_inventory_control_evidence.py:88`) are untouched. If a later change does add or delete a route, update: `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`, both count assertions, the required-route set in `test_audit_inventory_manifest.py:18-48`, and `saas-launch-route-matrix.spec.ts:134-172`.

### PR 0 — Attendance uses the class date (S, backend)

- Files: `mongo_student_repo.py`, the contract test file above.
- Tests: §5.5.
- Admin notices: the At risk count on Students changes, usually upward. Last-seen dates and attendance percentages change. Tell the owner the day before.
- Coach and parent: no change.
- Deploy notes: no migration. Include the prod count of recent marks without `occurrence_id`.
- Rollback: revert the commit. No data is written, so the old numbers return at once.

### PR 1 — Sidebar groups, icons, subtitles (S, frontend)

- Files: `components/admin/screen-meta.ts`, `components/admin/screen-meta.test.ts`, `components/ds/icons.tsx`, `app/(admin)/layout.tsx` (testid from `id`), `e2e/specs/admin-shell.spec.ts`. Manual: `DESIGN.md:302` in the main checkout.
- "Users" keeps its label in this PR. It becomes "Staff" in PR 3, when the list matches the name. Its new icon and group land now.
- Assertions that change:
  - `admin-shell.spec.ts:710-714`: `"WORK"`, `"MONEY"`, `"COMMS · OPS"` become the six group names. The `/waivers/i` link check at `:717` still passes.
  - `screen-meta.test.ts:121`: Families breadcrumbs become `["Admin","People","Families"]`.
  - `screen-meta.test.ts:124-128`: title "Family", breadcrumbs `["Admin","People","Families","Family"]`.
  - `screen-meta.test.ts:35-50` uses its own fixture groups; no change.
- Tests to add (vitest): every nav `id` is unique; every `icon` key exists on `Icon`; group order is the six names; the owner-only set is unchanged (the existing test at `:52-64` already pins it).
- No change needed: `saas-launch-route-matrix.spec.ts` (routes and page testids only), `admin-students`, `admin-family-billing`, `tuition-discounts` (no nav, title or subtitle assertions), `local-auth-qa.spec.ts:121` (the Messages heading is unchanged).
- Admin notices: the sidebar has six headings, Inbox sits under Dashboard, Families is next to Students, and Students, Families, Users and Waivers each have their own icon. Every page opens at the same address as before.
- Coach and parent: no change. `screen-meta.ts` is imported only by `app/(admin)/layout.tsx`.
- Rollback: revert. No data, no API.

### PR 2 — Users list filter (S, backend)

- Files and tests: §4.1.
- Admin notices: nothing. The param is unused until PR 3.
- Coach and parent: no change; the route is under `require_persona("admin")`.
- Rollback: revert. If PR 3 is already live, revert PR 3 first, or the Staff list will ignore the unknown param and show parents again, which is harmless.

### PR 3 — Users becomes Staff (S–M, frontend)

- Files: `screen-meta.ts` (label, title, subtitle, breadcrumbs for `/admin/users`), `components/admin/AdminUsersDirectory.tsx` (pills at `:27-32`, `?role=parent` banner, pay and assignment line, "Parent accounts" link, success message link), `lib/api/admin.ts`, `users/[userId]/page.tsx` (roles-based coach gate, Family link), `families/[parentId]/FamilyHeader.tsx` ("Account & login"), `families/page.tsx` ("Parent accounts" link), `next.config.ts:69`, `parents/page.tsx`, `admin-shell.spec.ts`.
- Pills become: All staff, Coaches, Assistant coaches, Admins. "All staff" calls the list with `exclude_role=parent`. The Parent option in Add user stays.
- Assertions that change:
  - `admin-shell.spec.ts:1013-1030`: the `/admin/parents` test waits for `/\/admin\/families$/` and asserts the families page testid instead of `admin-users`. Its stubs must cover the families list call.
  - `admin-shell.spec.ts:990-1008` (`/admin/coaches`): unchanged.
  - Any mock of `**/api/v2/admin/users*` that matches the URL exactly must accept the new query string. Check `stubAdminBff` and `saas-launch-route-matrix.spec.ts`.
- Tests to add: e2e that `/admin/users?role=parent` shows the banner and still lists parents; e2e or vitest that a user with roles `["parent","coach"]` appears under All staff and gets the pay-rate panel; vitest for the new pill list.
- Admin notices: "Users" is now "Staff" and lists coaches and admins only. Parents are found under Families; a parent's login is one click away through "Account & login". An old `/admin/parents` bookmark opens Families, or, in a browser that cached the old redirect, the parent list with a banner pointing to Families.
- Coach and parent: no change.
- Rollback: revert. The redirect entry is `permanent: false`, so the rollback is not pinned in anyone's browser.

### PR 4 — Deep links and entry points (S, frontend, plus the one-line families fix)

- Files: `students/[studentId]/page.tsx`, `students/page.tsx`, `families/[parentId]/StudentsPanel.tsx`, `messages/page.tsx`, `sessions/page.tsx`, and either `composition/admin.py:1987` (net-zero) or `families/page.tsx`.
- Tests: `tuition-discounts.spec.ts` gains a check that the family page's "Recurring discount" link opens the student page on the discount tab; vitest for tab parsing from the URL and the default when the value is unknown; `admin-students.spec.ts` gains a check that the Parent cell links to `/admin/families/{id}`; a backend test that a student with an empty `parent_id` produces no Families row (if the fix is made in the backend).
- Admin notices: clicking a parent's name on Students opens the family. "Recurring discount" lands on the right tab. Refreshing a student page keeps the tab. Messages has quick links to Broadcast, Direct message and Email campaign. Sessions has a Waitlist link. The blank row on Families is gone.
- Coach and parent: no change.
- Rollback: revert.

### Optional, not recommended now — pending count on the Inbox nav row (S–M)

`layout.tsx:289-300` already renders `count` and `urgent`, and `GET /admin/inbox/counts` exists. But the shell fetches no data today by design (`screen-meta.ts:1-7`). A badge means a client-side query in the admin layout on every page, and every admin e2e spec that asserts a clean console would need a stub for it; an unstubbed shell poll has broken those specs before. The Inbox page already shows counts per tab. Do this only if the owner asks for the badge.

## 7. Risks

1. **At-risk numbers jump on the day PR 0 lands.** Correct but visible. Mitigate with a heads-up and a release note that says why.
2. **Cached 308 on `/admin/parents`.** Cannot be cleared. Covered by keeping `?role=parent` as a working page with a banner.
3. **Parents with no children** have no list entry except the "Parent accounts" link. Acceptable for now; the proper fix is a Families view for them, which is later work.
4. **Staff still highlights when viewing a parent's account** at `/admin/users/{parentId}`, because the match is on the path prefix. Accept it; the breadcrumb reads Staff, and the page has a Family link.
5. **Three redirect stubs still render the admin layout** before forwarding: `/admin/waitlist`, `/admin/registrations`, `/admin/requests`. This is the pattern that hit the Cloudflare Workers ceiling on Dues (#689). It is outside this spec, but this work adds a Sessions link to the waitlist, so that link must point straight at `/admin/inbox?tab=waitlist` and never at `/admin/waitlist`. Moving the three stubs into `RETIRED_ROUTE_REDIRECTS` is worth its own issue; `registrations` and `requests` pass a `tab` query through, so check how config redirects merge query strings in the installed Next version (`node_modules/next/dist/docs/`) first.
6. **New icons** must be drawn in the same 24-unit stroke style as the rest of `icons.tsx` and stay legible at 16px on the night sidebar.
7. **Six groups is still twice the captions of today.** Check the phone drawer at 390×844 and the desktop sidebar at 768px height for scroll.
8. **Worktree drift.** The assigned worktree branch was 31 commits behind `origin/main`. It carried the pre-Inbox nav. Anyone implementing from a fresh worktree should confirm it is on current main first.

## 8. Open decisions for the owner

1. **"Students" or "People" for `/admin/students`.** Recommend **Students**. The list shows children only; "People" promises parents and leads that are not in it. Rename it when the list really holds them. The group caption PEOPLE already carries the pillar name.
2. **Staff inside PEOPLE, or its own STAFF group.** Recommend **inside PEOPLE** (six groups). A one-item group adds a caption and height for no gain. If the four pillars must each be a visible heading, a seventh group is a one-line change in `screen-meta.ts`.
3. **Families under PEOPLE or left under MONEY.** Recommend **PEOPLE**. After the Parents pill goes, Families is the only list of parents, and the family page is the record for the household. If left under MONEY, everything else in this spec still works; only row 6 of the table and two breadcrumb lines change.
