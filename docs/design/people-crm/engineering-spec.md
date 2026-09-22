# People CRM: Engineering Spec

> Reconciled with `shape-brief.md` on 2026-09-22 (see the Reconciliation log at the end). Code citations were re-checked against `origin/main` at b038dd297 where noted; every other line number carries over from the 78184a77b draft and must be re-checked before implementation starts. Companion documents: `students-families-users-memo.md` (why Students stays its own page) and `docs/design/admin-ia/sidebar-regroup-spec.md` (the PEOPLE sidebar group, in flight on another branch).

## 1. Concept and principles

- **The family record is the account and each child is a member.** A family record is keyed by a parent id. There is no family entity in the database today: `list_parents` builds family rows by walking students (composition/admin.py:1998 on b038dd297). On each request the backend resolves one alias set per parent: `user_id`, `firebase_uid`, `_id` and `parent_user_id` on applications and trials. Every read in this spec, including the family billing read model, must be alias-aware. Today that read model is not: `_invoices` matches only the exact stored value through `"$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}]` (family_billing_read_model.py:627-632 on b038dd297). That `$or` across two fields is the same shape as the partial-index incident behind #878 and #894, so the alias-aware fix in Phase 2 issues one equality lookup per alias and merges, never a single `$or` or `$in` across partial-indexed fields.
- **A contact can exist before an account does.** Phone-only and website inquiries live in `crm_contacts`. It is **one store shared with the public tenant page**: the anonymous trial-request form in `docs/design/public-tenant-page/brief.md` is the first writer of the collection and creates the same record with source `website`. This spec adopts that record; it does not define a second one. A contact becomes part of a family record when a parent user is created or linked.
- **One record, many views.** There is one family record page. Today, Families, Pipeline and Follow-ups are views over the same family index; Students stays its own page and reads the same index for its Parent column.
- **Staff are excluded from the index.** A user is included only when `roles` contains `parent`, or when a student, application or trial references them as a parent. Every CRM route is `require_persona("admin")`. Coaches get only a narrow safety card (Section 4).
- **Derive state instead of storing it.** The family stage is a roll-up of `derive_lifecycle()` (contexts/enrollment/domain/lifecycle.py:126). The timeline is merged at read time. Only notes, follow-ups, family contacts, logged contacts, tags and the optional send log are new storage.
- **Show a warning instead of failing.** Each secondary source is wrapped in `_secondary()` (family_billing_read_model.py:409), and independent sources run under `asyncio.gather`. A failed source shows a warning in the UI, never a zero.
- **Keep business logic out of the wiring layer.** A new `contexts/crm` context holds the logic. `application/` holds the stage roll-up, search, follow-up rules and timeline merge and dedupe as pure functions. `infrastructure/` holds the read model and the repositories. `composition/families_crm.py` is wiring only and is registered in main.py the way `compose_admin_families` is (main.py:53, :712). It adds zero lines to composition/admin.py, which is at 4,485 of its 4,500-line budget (test_composition_is_wiring.py:27, `ADMIN_COMPOSITION_LINE_BUDGET`); 15 lines of headroom is not enough for anything in this spec.
- **Add no new frontend routes.** The count stays at 92, which the manifest-equality tests enforce (test_inventory_acceptance_coverage.py:153, test_inventory_control_evidence.py:88). Every view in Section 3 is a `?view=` of `/admin/families` or an existing page.
- **Coach notes are read-only here.** The CRM shows coach notes from the existing #665 data on the child drawer and in the Timeline, tagged with the coach's name. It never writes them. Decided by the owner 2026-09-20.

## 2. Information architecture

Decided by the owner 2026-09-22: the sidebar gets a **PEOPLE** group holding **Students**, **Families** and **Staff** as three separate items. The Students label stays on `/admin/students`. "Users" is relabelled **Staff**. Families is not renamed "People" (sidebar-regroup-spec.md §1 row 6). The brief's People section is realised as the sub-nav of the Families page plus the existing Students page.

| Route | Role |
|---|---|
| `/admin/families` | The People section. The sub-nav view is chosen with `?view=today\|families\|pipeline\|follow-ups`; `today` is the default. |
| `/admin/families/[parentId]` | The family record, with `?tab=`. A `c_`-prefixed id opens a contact-only record (a lead). |
| `/admin/students` | The Students view, kept as its own page. The People sub-nav links to it. |
| `/admin/students/[studentId]` | The full child page. All deep child writes stay here. |
| `/admin/users` | Relabelled "Staff". It remains the account editor for any user, parents included. |
| `/admin/reports` | Reports. Linked from People, not a People sub-nav item. The four CRM reports in Section 3 are added as report cards here. |

**Navigation (screen-meta.ts).**
- PEOPLE group: Students, Families, Staff. Labels and grouping follow sidebar-regroup-spec.md; this spec does not re-derive them.
- "Users" becomes **Staff**.
- Each item gets its own icon. Update screen-meta.test.ts. Nav testids are built from the label, so add a stable `id` per item first (sidebar-regroup-spec.md §1 row 7).

**Redirects.** Old people routes forward through `RETIRED_ROUTE_REDIRECTS` in frontend/next.config.ts:60-71. A layout `redirect()` hit the Cloudflare Workers resource ceiling (#689, #827). Each `page.tsx` stays as a fallback so the manifest still matches.
- `/admin/students` is **not** redirected. The 2026-09-22 decision keeps it as the Students page.
- `/admin/parents` is already a cached 308. Change its destination to `/admin/families?view=families`, and also change the fallback `redirect()` in parents/page.tsx:14. Browsers that cached the old 308 will keep landing on Staff.
- `/admin/users?role=parent` keeps a banner that links to Families. Remove the Parents pill. Add a backend `?exclude_role=parent` filter, so coaches whose primary role is parent stay visible.

**Deep links.**
- `/admin/students/[id]` reads `?tab=` through `parseStudentDetailTabId` (components/admin/StudentDetailTabs.tsx:26). Today it uses `useState("overview")` (students/[studentId]/page.tsx:61). Write the tab back with `router.replace`.
- The family record accepts `?tab=overview|details|messages|billing|timeline`.
- `/admin/families?view=pipeline&stage=trial_booked` and `?view=follow-ups&bucket=overdue&who=mine` are the Pipeline and Follow-ups deep links.

**Cross-links.**
- The Parent cell on the Students page links to the family record.
- `FamilyBillingLink` keeps its "Family" label.
- FamilyHeader gets an "Account & login" link to Staff.
- The child page gets a "Family" breadcrumb.
- The Families view header gets a "Reports" link to `/admin/reports`.

**Coach-facing links.**
- Coach pages never link into `/admin/families`. The one exception is an "Open family" link shown only when `is_coach_supervisor` is true.
- Admin screens that show a coach link to Staff.

## 3. The People section: five views plus Reports

The names below are the brief's names and are used verbatim in the UI. Desk: the sub-nav is a tab strip under the People title. Phone: a scrollable strip, 44px targets.

### 3.1 Today (default)

The existing Today queue, unchanged in shape: reason-driven rows with one primary action each, preview before anything reaches a parent.
- Adds an assignee avatar or initials per row.
- Adds a **Mine / Everyone** switch. "Mine" filters on `assignee_id == current admin`. The switch is remembered per browser.
- Rows come from the same index as Families plus open follow-ups due today or earlier (Phase 4).

### 3.2 Families

**Layout.** Top to bottom: scope tiles, a Class filter (session picker), search, Groups, the table with multi-select, and the "Add family" and "Add inquiry" buttons.

**Scope tiles: Active, Leaving, Left only.** They map onto the family stage of Section 6:

| Tile | Family stage |
|---|---|
| Active | `active` |
| Leaving | `at_risk`, `on_hold`, `paused`, `pending_cancel` |
| Left | `left` |

Tiles come from `GET /admin/families/summary`, are computed over the unfiltered set, and count each family once. Lead-only records (`never_enrolled`) are not on a tile; they live in Pipeline.

**Data path.** The backend runs three academy-wide batched reads under `gather`: open invoices with their due dates grouped by parent, the latest failed payment attempt per parent, and the registration and card-on-file state. It builds the index once per request. The frontend loads that index and filters, sorts and searches it client-side. Keystrokes never call the server again. A 60-second TTL cache keeps this safe for multi-tenant use. Money data is never built one family at a time.

**Search.**

| Key | Source |
|---|---|
| Child names, with prefix match on first name | students |
| Parent name and email | users |
| Family contacts (name, email, phone) | `family_contacts` |
| Legacy parent fields | `parent_name`, `guardian_name`, `parent_email` on the student record |
| Phone (digits only, last 7 to 10 digits) | `users.phone`, `parent_profile.phone` on applications, `family_contacts.phone_digits`, `crm_contacts.phone_digits` |
| Prospective children | application `child_profile`, `trial_requests.prospective_child_name` |

- Name matching uses `full_name_key`.
- **When the query matches a child, that child is the result row.** The parent appears as secondary text, and the row links straight to `/admin/students/{id}`.
- Search covers every stage and every view. A match outside the current view carries a chip such as "In Pipeline".

**Desk columns, all sortable:** parent name and phone; child chips with lifecycle badges; stage; balance; last contact (channel and who); next follow-up (due date and assignee); tags; card and autopay. Sort runs before pagination.

**Filters** (chips above the table, combinable, kept in the URL): Overdue (an open invoice past its due date); No card (operational stage and registration not `card_on_file`); Not attending (any child with a live `active` enrollment, at least 2 non-cancelled occurrences in the last 21 days, and no `present` or `late` mark; requires Phase 0); Missing info (a child missing a CHILD_REQUIRED field, shared/profile/completeness.py:29-35, or the waiver check from #785 reporting no signature or a signature by a different parent); Needs attention (the union of every risk flag with a reason chip per row, including an open follow-up due today or earlier from Phase 4); tag.

**Groups.** A Group is a saved filter (scope, class, filter chips, tags) with a name, stored per academy in `family_groups`. Examples: "Sat Advanced parents", "Overdue with no card". Opening a Group applies its filter; a Group message resolves the current members at send time.

**Bulk actions on selected rows or a Group.**
- **Message** uses the `SelectedRecipientsAudience` (communications/domain/models.py:66 on b038dd297), newly exposed on `POST /admin/campaigns`. Before any send the UI shows the resolved recipient count and the skip list: families with no email, and suppressed addresses (#778). Recipients follow the notice audience rules in Section 4 (primary parent plus contacts with "Gets notices").
- **Add tag** applies a tag to every selected family.
- **Export** downloads the visible columns as CSV. Front desk exports carry no amounts.
- **Copy phones** and **Copy WhatsApp link** (group link when a Class filter is set) stay as secondary actions.

**Session campaigns (fix).** The session audience today resolves only enrollments whose status is `"active"` (mongo_audience_resolver.py:90) and looks up parents by `user_id` only (:110). Change it to ROSTER_VISIBLE enrollments and alias-aware parent lookup.

### 3.3 Students

The existing `/admin/students` page, kept as its own route (owner decision 2026-09-22). It respects the People scope and Class filter when reached from the sub-nav (`?scope=`, `?session=`). Columns: child; age; level; classes with badges; last attended; 30-day rate; dues; parent (linked). A "Children without a family" callout lists rows where `parent_id == ""`.

### 3.4 Pipeline

A board with columns **Inquiry, Trial booked, Trial done, Registered, Enrolled**, one card per prospective or current child in the funnel. The columns map onto the per-child pipeline status of Section 6:

| Column | Per-child status |
|---|---|
| Inquiry | `lead` with no trial request |
| Trial booked | `trial` with an approved trial request whose occurrence has not passed |
| Trial done | `trial` with a completed trial (Came / Didn't come recorded) or a passed occurrence |
| Registered | `trial` with an application in PENDING_APPROVAL or later, or APPROVED without an enrollment yet |
| Enrolled | `enrolled` (the card leaves the board after 7 days) |

- **Card:** parent, child and age, source, lead age in days, last contact, next step, assignee.
- **Sources:** `whatsapp_or_phone`, `referral` (records `referrer_parent_id`), `website` (written by the public tenant page), `other`. Legacy system sources (signup, application, trial, waitlist) are shown as "Other" with the system name as secondary text.
- **Cold** after 14 days without contact: a chip, not a stage.
- **Quick add lead** from a phone: name, phone, child, source. Writes `crm_contacts`. Duplicate warning on phone or email with "Open existing family".
- Move a card **by buttons** (Move to ...), never drag only. Moves that correspond to a real write (approve trial, Came / Didn't come) call the existing use cases; moves without one write `crm_contacts.pipeline_override` with author and time so the board never lies about the system state.
- On a phone the board becomes a **stage switcher with a list**.

### 3.5 Follow-ups

All follow-ups across families, in buckets **Overdue, Today, Upcoming, Done**.
- **Mine / Everyone** switch, reassign, change due date, complete, and a link to the family on every row.
- Automatic follow-ups (trial occurrence passed with no application after 7 days; card declined) carry an "automatic" label and are idempotent (Section 5).
- Empty state: "Nothing due".
- Backed by `GET /admin/follow-ups?assignee=me|all&bucket=` (Section 5).

### 3.6 Reports (linked, not a sub-nav item)

Four report cards on the existing `/admin/reports` page:
- **Inquiry to enrolled by source**, per month.
- **Families lost and why**, by month, with how long they stayed (`left_reason`, `left_at`, joined date).
- **Attendance risk by class and coach** (the Not attending flag grouped by session and assigned coach; requires Phase 0).
- **Money owed by age band** (1 to 30, 31 to 60, older), from the open-invoice aggregation of 3.2.

Small, honest charts; every number links to the list behind it (a Families or Pipeline deep link). The money report is hidden from staff without billing permission. No new route: the cards are added to the existing reports page.

## 4. Family record

Tabs: **Overview, Details, Messages, Billing, Timeline.**

**Header.**
- Parent name and stage chip; per-child pipeline chips; risk-flag chips.
- Tap-to-call phone and mailto email.
- Registration state and a "joined" date.
- Child chips that open the drawer.
- Balance, credit and autopay with the card's last 4 digits (hidden for front desk, who see an "Owes money" flag with no amount).
- Last contact and who.
- A `warnings[]` banner and the email suppression banner (#778).
- Phone: a pinned bottom action bar.

**Quick actions.**

| Action | Implementation | Who |
|---|---|---|
| Call, Email | Client-side links | all staff |
| Message | Opens the Messages compose (below) | all staff |
| Log a call, Spoke in person | One tap plus a short note, writes `family_contact_log` | all staff |
| Add note, Add follow-up | New | all staff |
| **Add child** | New `POST /admin/families/{id}/students` taking name, DOB, emergency contact and medical notes, with `parent_id` filled in. It creates a student with no enrollment. Enrollment then goes through the existing admin Enroll dialog. | all staff |
| Record payment | Opens `payments/buckets/RecordPaymentDialog` (families/[parentId]/page.tsx:31,352) for one invoice | owner only |
| Send login invite | `/admin/users/{id}/login-invite` (directory_routes.py:307) | all staff |
| Create trial | For a contact or a prospective child: an admin-created trial request | all staff |

**Staff tiers (decided by the owner 2026-09-22): owner, billing, front desk.** Front desk sees an "Owes money" flag with no amounts, no Billing tab, no Record payment, no money report. Billing sees every amount, invoice and report. **Money-moving actions are owner-only:** Record payment, charge, refund, void, add charge, one-time discount, autopay on or off. Billing is read-and-report for the billing tier. This is narrower than the brief's "Billing and owner see everything" and is enforced on the backend with the existing owner gate (test_owner_gate_policy.py), not only hidden in the UI. A "Viewing as" switch exists only in the prototype.

**Tabs.**

| Tab | Shows | Source | Status |
|---|---|---|---|
| Overview | Children first (a card per child with lifecycle badge, classes, last attended), money owed, open follow-ups with assignee, pinned notes, last contact and who, the 10 latest timeline items, and the pipeline card for leads and trials | `GET /admin/families/{id}` | needs new endpoint |
| Details | Primary parent; **family contacts** list (name, relationship, email, phone, **Gets notices**, **Gets invoices (opted in)**, can pick up); home address; preferred channel; how they heard about us and referrer; tags; login and invite state with "Send login invite". Inline edit with field-level errors. Replaces the old Account tab. | `GET /admin/users/{id}` (directory_routes.py:92), PATCH at :235, plus `family_contacts` and `family_details` | exists in part; contacts and details are new storage |
| Messages | One thread per family mixing app emails (DMs, campaign deliveries, notice sends, invoice emails) and staff-logged WhatsApp, SMS, calls and in-person talks, each with author and time | messages, message_deliveries, parent_digest_sends, absence_notice_sends, enrollment_hold_notice_sends, win_back_notice_sends, `invoices.email_provider_message_id`, plus `family_contact_log` | logs exist but are not exposed; the log is new storage |
| Billing | Enrollments, invoices, credits, autopay, Fix something | `GET /admin/families/{id}/billing` (families_routes.py:66), made alias-aware | exists |
| Timeline | The feed from Section 5, including read-only coach notes with the coach's name | `GET /admin/families/{id}/timeline` | needs new endpoint |

**Second parent and family contacts (decided by the owner 2026-09-20).** A family is one parent account. Extra contacts are rows in `family_contacts` with two independent switches:
- **Gets notices.** When on, the contact's email is added to the family's notice audience: parent digests, absence, hold, win-back and campaign sends. Implemented in one place, the audience resolver (mongo_audience_resolver.py), by extending the per-parent recipient expansion; the `SelectedRecipientsAudience` and session audiences inherit it.
- **Gets invoices (opted in).** Off by default. When on, the contact's email is added to the invoice email audience (invoice send, dunning, receipt). Payment links and autopay still belong to the primary payer; the contact receives a copy, never a separate payable link. Implemented where invoice emails resolve their recipient list, behind the same helper.
- No second guardian login is created. Contacts are never users.

**Pipeline card.** Shown on the Overview for leads and trials.
- Approve or Deny the trial inline, using the same use case as `/admin/inbox?tab=trials`.
- The assigned occurrence date.
- **Came / Didn't come.** This writes the trial status `completed`, which no code writes today (mongo_trial_request_repo.py:92).
- **Send registration link.**
- **Review application**, which links to the registrations inbox.

**Messages compose.** Picks a channel. **Email** sends from the app after a preview. **WhatsApp** and **SMS** open the staff member's own app with the text pre-filled (`wa.me` and `sms:` links) and then ask "Did you send it?" to log it; a dismissed prompt leaves a "not logged" row the staff member can complete later. **Send from the app (coming)** is shown as a disabled channel with a one-line explanation, never as working (owner decision 2026-09-20: app-sent SMS and WhatsApp are a later phase). Saved templates.

**Money summary.**
- One row per open invoice: a line for each child and month, the due date, the reason the last charge failed, and a Record payment button (owner only).
- Out of scope: splitting one payment across several invoices, and recording an advance payment as credit. The UI says so.

**Attendance correction.** A new `PATCH /admin/occurrences/{id}/attendance/{student_id}` calls the existing correction use case (correct_attendance.py). Today that use case is reachable only from the coach surface (coach/attendance_routes.py:74-100).

**Child drawer vs child page.**
- The drawer shows the child's read-only card (profile, age, level, medical, emergency contact, waiver, enrollments with `hold_return_on`, attendance with class date and session title, each row with a **Correct** action, a one-line pathway summary, and **coach notes read-only with the coach's name**, from #665 data) plus these actions:
  - **Hold child:** puts every live enrollment on hold with one return date.
  - **Change class**
  - **Open full page**
- The children read is one batched call inside the family endpoint. It reuses the student view (views.py:149) and progress, passport and certificates (progress_routes.py:228,248,539); `hold_return_on` is added.
- Hold confirmation shows a **next invoice preview**, produced by running the monthly billing generator in dry-run mode. The preview is never re-derived separately, because billing does not use the canonical BILLABLE set (enrollment/domain/models.py:175-181; mongo_monthly_billing.py:141-160).
- Every other write stays on `/admin/students/[id]?tab=`.

**Left families.** A family whose stage is `left` shows reason for leaving, date, time with the academy, and a win-back follow-up (created automatically when the reason is recorded). `left_reason` and `left_at` live in `family_details`.

**Coach safety card.** A narrow card on the coach passport page shows emergency contact, medical notes and pickup phone. It has its own access rule: the coach must be assigned to one of the child's sessions. The rest of the CRM stays admin-only.

**Real forms:** Add family, Add inquiry, Add child, Add contact. Every form warns on a duplicate phone or email with "Open existing family". Errors sit next to the field, never toast-only; every write confirms with a toast and Undo where reversible.

**Empty states.**
- **No children:** application and trial children appear as ghost cards labelled "From registration, not enrolled". Actions: Add child, Review application.
- **No card:** the billing-setup panel with "Send billing setup invite". Autopay is hidden.
- **Lead with no parent account:** a `crm_contacts` record (name, phone, optional email, source, including `website` leads from the public tenant page) opens at `/admin/families/c_{contact_id}`. Notes, follow-ups and trials attach to the contact. "Convert to family" creates a parent user when an email is known, because CreateAdminUserRequest requires one (interfaces/admin/views.py:237-242), and re-keys the contact's notes and follow-ups.
- **Lead with no email:** Message offers WhatsApp, SMS and call only; the email channel is disabled with the reason.
- **Unlinked children** (`parent_id == ""`): the "Children without a family" callout on the Students page.

## 5. Timeline, notes, follow-ups, contacts

**Timeline.** `contexts/crm/application/timeline.py` merges the sources below.
- `build_timeline` (family_billing.py:708) is called as one source. It is not extended.
- Each source is fetched newest-first with a limit of 200 inside `_secondary`, and all sources run under `gather`.
- The merged feed is sorted and cut to 200.
- Times pass through `_as_utc`, which prevents the #706 failure.

| Kind | Events | Source |
|---|---|---|
| money | invoices, payments, failures, dunning, admin money actions | family billing timeline |
| lifecycle | enrolled, moved, held, returned, paused, dropped, waitlisted, promoted | `enrollment_events` queried by `student_id $in` (the billing source queries by `enrollment_id` only, family_billing_read_model.py:795-810 on the older draft). `occurrence_cancelled` entries are collapsed. |
| attendance | absent marks and corrections, dated by `session_occurrences.start_at` | attendance; correction history comes from the outbox event, because the row keeps only the last `previous_status` (correct_attendance.py:12-13) |
| requests | absence notices, pause, cancel, makeup, trial | the request collections |
| registration | application started and decided, waiver signed | onboarding_applications, waiver_signatures |
| comms | DMs, campaigns, digests (muted), notice sends, invoice emails, logged WhatsApp, SMS, calls and in-person talks | the logs listed in Section 4 plus `family_contact_log` |
| coach | coach notes, read-only, with the coach's name | the #665 coach-notes data; never written from the CRM |
| admin | profile edits, parent change, pathway placement, roles, Stripe reconcile | `audit_logs` with an **action allowlist** (this excludes `user_logged_in`, mongo_login_audit_recorder.py:53-62), keyed on parent, student **and enrollment** ids |
| crm | notes, follow-ups, tags, contact conversion, pipeline moves | new collections |

**Dedupe.** One approved pause can produce a request decision, an enrollment event and an autopay change. Entries with the same `enrollment_id` inside a 10-minute window collapse into one.

**Children who moved families.** After a parent change (#785), settled invoices stay with the old family record. The new family's timeline shows a "Moved from family X" entry built from the parent-change audit row. The old family's timeline shows "Moved to family Y".

**Notes.**
- `family_notes`: `{note_id, academy_id, parent_id|contact_id, student_id?, body, author_id, pinned, created_at, updated_at, deleted_at, deleted_by}`.
- Endpoints: `GET` and `POST /admin/families/{id}/notes`; `PATCH` and `DELETE .../notes/{note_id}` (DELETE is a soft delete).
- Every write is scoped by `(academy_id, family_id, note_id)`.
- Migration: each non-empty `students.notes` value is copied into a pinned note tagged with the child. After that, `students.notes` becomes read-only on the child page, with a link to the family's notes.

**Follow-ups.**
- `family_follow_ups`: `{follow_up_id, academy_id, parent_id|contact_id, student_id?, title, detail, due_at, assignee_id, status, source, source_ref, created_by, created_at, completed_at, completed_by}`. `source` is `manual` or the automatic rule name; the UI labels non-manual rows "automatic".
- Endpoints: `GET` and `POST /admin/families/{id}/follow-ups`; `PATCH /admin/families/{id}/follow-ups/{follow_up_id}`; `GET /admin/follow-ups?assignee=me|all&bucket=overdue|today|upcoming|done`, which feeds the Follow-ups view and the Today queue.
- `assignee_id` must belong to an admin in the same tenant.
- A unique partial index on `(academy_id, source, source_ref)` where status is open makes automatic follow-ups idempotent. The fake store used in tests must raise on a duplicate key the way the real one does.
- Automatic rules: the trial's assigned occurrence `start_at` has passed and there is no application after 7 days; a card was declined; a family was marked left (win-back).

**Family contacts, details, tags, contact log.**
- `family_contacts`: `{contact_id, academy_id, parent_id, name, relationship, email?, phone_digits?, gets_notices, gets_invoices_opted_in, can_pick_up, created_at, updated_at}`. Endpoints: `GET`, `POST /admin/families/{id}/contacts`; `PATCH`, `DELETE .../contacts/{contact_id}`.
- `family_details`: `{academy_id, parent_id, address?, preferred_channel, heard_about_us?, referrer_parent_id?, tags[], left_reason?, left_at?, updated_at}`. One document per family, upserted by `PATCH /admin/families/{id}/details`.
- `family_groups`: `{group_id, academy_id, name, filter, created_by, created_at}`.
- `family_contact_log`: `{log_id, academy_id, parent_id|contact_id, channel, direction, body?, author_id, logged_at, sent_confirmed}`. Channel is `whatsapp`, `sms`, `call` or `in_person`; email is never logged here because the app sends it.

**Leads.** `crm_contacts`: `{contact_id, academy_id, name, phone_digits, email?, source, child_name?, child_age?, requested_session_id?, pipeline_status, pipeline_override?, referrer_parent_id?, converted_parent_id?, created_at}`. This is the shape the public tenant page writes (source `website`); the CRM adds `referrer_parent_id` and `pipeline_override` and reads everything else as written. One collection, one migration, one create-contact use case, owned by whichever PR lands first.

**Indexes and validators.** One migration (numbered after the latest applied on main at the time) adds:
- `enrollment_events (academy_id, student_id, occurred_at)`
- `audit_logs (academy_id, entity_type, entity_id, created_at)`
- `pause_requests (academy_id, parent_id, created_at)`
- `absence_notices (academy_id, student_id, submitted_at)`
- the notes, follow-ups, contacts, details, groups and contact-log indexes and validators

**How migrations reach production (decided by the owner 2026-09-22).** Production does not run migrations at boot (`V2_RUN_MIGRATIONS_ON_BOOT: "false"`, production.yml:117). Each migration in this spec ships through an explicit **migrate job in `production.yml`** that runs before the deploy step, after the live Fly runtime value of the boot flag has been confirmed and whatever overrides `fly.toml` removed. Dormant validators reject writes anywhere (#657), so the migrate job runs and is checked before the feature flag is turned on. No hand-applied SSH steps.

**Who can see these.** Admins and owners only, tiered as in Section 4. Coach notes appear read-only with the coach's name (owner decision 2026-09-20); private coach notes stay private (migration 0167), only notes the coach marked shared are shown.

## 6. Lifecycle stage

**Per child.** `derive_lifecycle()` already returns one of `active`, `at_risk`, `paused`, `on_hold`, `pending_cancel`, `left`, `never_enrolled` and `trial` (lifecycle.py:47-56). Its R6 branch is extended to cover application, waitlist and trial states on the same enum, as the module's own comment plans. No parallel enum is added. Any new status set goes in enrollment/domain/models.py, and the AST scan in test_enrollment_status_predicates.py is widened to include `contexts/crm`.

**Per family.** The stage is the highest-ranked child state, in this order:

`pending_cancel > active > at_risk > on_hold > paused > trial > never_enrolled > left`

A contact-only record is `never_enrolled`, shown as "Lead". The Families scope tiles group these stages as Active, Leaving and Left (Section 3.2).

**Pipeline status per child and prospective child.** Values are `lead`, `trial` and `enrolled`. The table below lists every status the code has. A unit test iterates `get_args()` over each status type, so a new status fails the build.

| Source status | Pipeline |
|---|---|
| Application DRAFT, CHECKOUT_PENDING, CHECKOUT_EXPIRED, ABANDONED, DECLINED, REFUNDED, CAPACITY_FAILED_REFUNDING, CAPACITY_FAILED_REFUND_FAILED | lead |
| Application PENDING_APPROVAL, APPROVING, WAITLISTING, DECLINING (transient claim states, admin_registration_review.py:300), WAITLISTED | trial |
| Application APPROVED | enrolled once an enrollment exists; trial until then |
| Trial pending, approved, completed | trial |
| Trial denied | lead |
| Trial converted | enrolled when a registration is approved (self_service.py:242,262) |
| Waitlist waiting, offered (`_LIVE_WAITLIST_STATUSES`) | trial |
| Other waitlist statuses | lead |
| `crm_contacts` with no trial or application | lead |

The Pipeline board columns of Section 3.4 are a finer split of these three values. This mapping does not follow enrollment_funnel.py. The funnel counts applications, not families.

**Edge cases.**
- **Split families:** one child active and one left makes the family Active. Chips show the difference.
- **`students.status`:** this free-text field is ignored.
- **Cold lead:** a lead with no logged contact for 14 days gets a "Cold" chip (brief §4). It is not a separate stage.
- **Not attending:** computed per child. The family flag is set if any child qualifies.
- **Attended** means `present` or `late` everywhere, matching the rate calculation (mongo_student_repo.py:1715). Voided marks are excluded (sidebar-regroup-spec.md §1 rows 3-4).

## 7. Phased delivery

Every phase ships on its own and needs a release note with the three required sections and the real PR number. Every phase that adds storage runs its migration through the `production.yml` migrate job before its flag is enabled.

**Phase 0: attendance fix (S, backend).** Prerequisite for every attendance column and flag. Shipping as its own PR under sidebar-regroup-spec.md.
- Fetch occurrences with one `$in` on `occurrence_id`, and confirm there is an `(academy_id, occurrence_id)` index.
- "Last attended" becomes the latest `present` or `late` mark by class date.
- The rate window becomes 30 days on class date (today it is 90 days on `marked_at`, `_attendance_summaries`, mongo_student_repo.py:2116 on b038dd297).
- Exclude `voided` and legacy `is_deleted` marks.
- `_recent_attendance` (:1531) returns the class date and session title.
- **Ripple:** `last_seen_at` feeds the `at_risk` state, so `lifecycle_counts` and the tiles will shift. Tests and the release note must cover this.
- Tests: naive and aware datetimes, `at_risk` counts, the admin-students e2e.

**Phase 1: IA and links (S, frontend plus a small backend change).** Overlaps with sidebar-regroup-spec.md; build it once, there.
- PEOPLE group with Students, Families, Staff; icons; stable nav ids.
- Student `?tab=` support.
- Cross-links.
- The `/admin/parents` redirect (next.config and the fallback page).
- `?exclude_role=parent` on the backend and removal of the Parents pill.
- Session audience fix (ROSTER_VISIBLE, alias-aware lookup).
- Specs that change: screen-meta.test.ts, admin-shell.spec.ts, tuition-discounts.spec.ts.

**Phase 2: family index, Families view, search (L, backend then frontend).**
- `contexts/crm` read model with the stage roll-up, the R6 extension, alias resolution, batched money aggregations, the search index and the summary endpoint.
- Alias-aware family billing built from per-alias equality lookups (Section 1), with a test showing that a student stored under `firebase_uid` produces the same result in the list and in the Billing tab.
- Families view: scope tiles, sortable columns, filter chips that have data behind them (the follow-up clause of Needs attention waits for Phase 4), Class filter, multi-select, Message with recipient count and skip list, Export.
- Signer-aware waiver check.
- No `/admin/students` redirect and no manifest rewrite.
- Changes: saas-launch-route-matrix.spec.ts gets mocks for `/api/v2/admin/families*`; the admin-students and admin-family-billing e2e specs are updated; unit tests cover the precedence and the status mapping.

**Phase 3: family record (M, frontend plus backend).**
- Tabs Overview, Details, Messages (read side), Billing, Timeline; batched children read; drawer with read-only coach notes; empty states.
- Add child endpoint.
- Admin attendance correction route.
- Pipeline card.
- Hold child with the dry-run invoice preview.
- Coach safety card and the supervisor link.
- Owner-only gate on every money-moving action, with a structural test.
- Changes: family-view.test.ts and the admin-family-billing e2e.

**Phase 4: contacts, details, notes, follow-ups, Today and Follow-ups views (M-L).**
- `contexts/crm` repositories and the migration, through the migrate job.
- `crm_contacts` adopted from the public tenant page if it landed first, otherwise built here in the same shape.
- `family_contacts` with the two switches, wired into the notice audience and the invoice email audience.
- `family_details`, tags, `family_groups`.
- `students.notes` copy and the read-only switch.
- Follow-ups view, Today assignee and Mine / Everyone, automatic follow-up rules, the Needs attention follow-up clause.
- Tests against real store semantics (duplicate-key raise on the idempotency index).
- A structural test that reuses `_iter_routes` and `_dependant_calls` from test_owner_gate_policy.py to assert `require_persona("admin")` on every `/families`, `/follow-ups` and `/crm` route.
- Tests for object scoping and assignee role validation.

**Phase 5: Pipeline board and unified timeline (L).**
- Pipeline view with move-by-buttons, quick add lead, duplicate warning, stage switcher on phone.
- Timeline adapters, the audit allowlist, coach-note source, dedupe, move entries and the index migration.

**Phase 6: Messages compose and Reports (M).**
- Read the existing send logs first.
- Messages thread with the WhatsApp and SMS handoff-and-log flow, "Log a call", "Spoke in person", templates, the disabled "Send from the app (coming)" channel.
- An optional `email_sends` log, written in `resend_send_port.py:139` with an explicit `academy_id` argument. It fails closed when the id is missing, because workers run without the tenant ContextVar.
- Suppressions stay global.
- The four report cards on `/admin/reports`, money report gated on billing permission.

**Later phase, not scheduled:** SMS and WhatsApp sent by the app (provider, parent consent and opt-out, templates, delivery status). Owner decision 2026-09-20.

## 8. Decisions taken and what remains open

**Decided.**
1. **Coach notes** are visible in the CRM read-only, on the child drawer and in the Timeline with the coach's name (owner, 2026-09-20). The coach safety card on the passport page stays as the coach-facing scope.
2. **Second parent:** family contacts with "Gets notices" and "Gets invoices (opted in)"; payment links stay with the primary payer; no second guardian login and no household entity (owner, 2026-09-20).
3. **Students label** is kept on `/admin/students`; Staff sits inside the PEOPLE sidebar group with Students and Families; Families is not renamed People (owner, 2026-09-22). The Phase 2 `/admin/students` redirect and manifest rewrite are dropped.
4. **Staff tiers** are owner, billing and front desk; money-moving actions are owner-only (owner, 2026-09-22).
5. **Migrations** ship through an explicit migrate job in `production.yml`, not by hand (owner, 2026-09-22).
6. **App-sent SMS and WhatsApp** are a later phase; until then handoff-and-log (owner, 2026-09-20).

**Open.**
1. **`crm_contacts` timing.** The public tenant page is planned as the first writer of the collection. If it ships before Phase 4, the CRM adopts its migration and use case; if not, Phase 4 builds them in the shape above and the public page adopts them. Either way there is one store. Recommendation: build the store with whichever lands first and do not wait for Phase 4.
2. **Reports placement.** Section 3.6 adds four cards to the existing `/admin/reports` page to avoid a route change. Confirm that the reports page is the right home, or that a Families-scoped reports block is preferred.

## Reconciliation log

Changes made on 2026-09-22 to bring this spec in line with `shape-brief.md` and the owner decisions of 2026-09-20 and 2026-09-22. Each line names the brief section it follows.

1. **Title and tenant name.** "Household CRM for ... Admin: Design Spec" became "People CRM: Engineering Spec"; the real academy's name is removed from the document (brief §3 name, §4 rename rule).
2. **"household" became "family record" everywhere**, including entity, collection, endpoint and file names (`family_notes`, `family_follow_ups`, `/admin/families/...`, `composition/families_crm.py`) and Phases 2, 4 and 5; the "FamilyBillingLink relabelled Household" item is dropped (brief §3 "family record", §7 "must not invent ... a household entity").
3. **Section 3 rebuilt as the five views plus Reports**: Today, Families, Students, Pipeline, Follow-ups, and Reports linked from People. The old `?view=` saved views (Households, Needs attention, Overdue, No card, Not attending, Missing info, Leads, Trials, Left, Students) became Families scope tiles and filter chips, the Pipeline board, and the Follow-ups view (brief §3 structural thesis, §4 People section items 1-6, §6 layout).
4. **Family record tabs** became Overview, Details, Messages, Billing, Timeline; Details replaces Account; Children, Notes & tasks and Comms folded into Overview, the child drawer, Messages and Follow-ups (brief §4 family record tabs).
5. **"Users" became "Staff"** in label, nav and prose; Staff sits in the PEOPLE sidebar group with Students and Families, and Families is not renamed People (brief §4 rename; owner decision 2026-09-22; sidebar-regroup-spec.md §1 row 6).
6. **Students label kept on `/admin/students`.** The Phase 2 redirect, the manifest rewrite and old open decision 3 are removed (owner decision 2026-09-22, which supersedes the brief's 2026-09-20 "retire it" line; noted in the brief).
7. **Second-parent switches** "Gets notices" and "Gets invoices (opted in)" added on family contacts and wired to the notice audience resolver and the invoice email audience; payment links stay with the primary payer; old open decision 4 (`guardians[]` on a household entity) removed (brief §7 decided 2026-09-20).
8. **Coach notes decided read-only in the CRM**, from #665 data, on the child drawer and Timeline with the coach's name; old open decision 1 removed (brief §7 decided 2026-09-20).
9. **`crm_contacts` stated as one store shared with the public tenant page**; source `website` added beside WhatsApp or phone, Referral and Other; the CRM adopts the record rather than defining a second one (brief §4 Pipeline sources; `docs/design/public-tenant-page/brief.md` rows 15, 181, 227).
10. **Staff tiers** owner, billing, front desk with money-moving actions owner-only, stated as decided and flagged as narrower than the brief's "Billing and owner see everything" (owner decision 2026-09-22; brief §4 permissions).
11. **Migrations** move from "applied by hand" to an explicit migrate job in `production.yml`; old open decision 5 removed (owner decision 2026-09-22; brief §7 operational step).
12. **Messages compose, handoff-and-log, "Send from the app (coming)"**, Left families fields, real forms and duplicate warning, Cold after 14 days (was 90), and Groups with recipient count and skip list added (brief §4 Messages, Left families, Real forms, Pipeline; §5 states).
13. **Code citations corrected** against b038dd297: `list_parents` is at composition/admin.py:1998 (was :1984); composition/admin.py is 4,485 of 4,500 lines (was 4,480); `SelectedRecipientsAudience` is at communications/domain/models.py:66 (was :120); `_attendance_summaries` is at mongo_student_repo.py:2116 (was :2123); the family billing read model's exact-match query is a `$or` across `parent_id` and `parent_user_id` at family_billing_read_model.py:627-632, not a `parent_id $in <aliases>` at :520-523/:627, and the Phase 2 fix must use per-alias equality lookups because that `$or` shape is the #878/#894 anti-pattern.
14. **Memo left unchanged.** `students-families-users-memo.md` agrees with the brief and the 2026-09-22 decisions (Students stays its own page; Users becomes Staff; no route changes).
15. **Prototype not included.** `people-crm-prototype.html` is left out of this change until it has had a full manual read for person names; it is only pattern-checked today.
