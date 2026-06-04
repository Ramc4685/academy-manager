# Admin Student Profile Redesign Design

## Status

Draft for user review.

## Problem

The current admin student detail page is useful but too form-led. It shows the
student identity, editable profile fields, current payment, enrolled sessions,
engagement, payment history, and parent reassignment, but the information is
spread across panels without a strong student-record structure.

Academy admins need a profile that supports daily student management:

- confirm whether a student is active, paid, attending, and correctly enrolled;
- update student profile and training information safely;
- find parent contact and compliance information quickly;
- move sessions or change parent accounts through guarded workflows;
- keep billing edits in billing-owned workflows.

## Current Behavior Found

The existing frontend route is
`frontend/app/(admin)/admin/students/[studentId]/page.tsx`.

Current BFF fields already available through admin student detail include:

- `student_id`
- `full_name`
- `parent_id`
- `parent_name`
- `parent_email`
- `parent_phone`
- `status`
- `date_of_birth`
- `level`
- `notes`
- `active_session_count`
- `attendance_rate`
- `last_seen_at`
- `dues_status`
- `enrolled_sessions`
- `payment_history`
- `current_payment`

Local seed data and backend collections also indicate useful student-management
fields that are not fully surfaced or mapped today:

- `skill_level`
- `age` or derived age
- `emergency_contact_name`
- `emergency_contact_phone`
- `medical_notes`
- `previous_experience`
- `t_shirt_size`
- waiver accepted status and date/version
- move history
- recent attendance rows

One current mapping gap is that seed data stores `skill_level`, while the admin
detail view exposes `level`. The redesigned profile should normalize this so the
UI does not show a blank level when skill data exists.

## Product Decision

Use a **Tabbed Student Record** for academy admins managing students.

The page should have a persistent top summary and five tabs:

1. **Overview**
2. **Training**
3. **Sessions**
4. **Billing**
5. **Family & Compliance**

The selected model favors depth and clean separation, but the top summary keeps
critical state visible so admins do not need to switch tabs just to see payment,
attendance, active session, or waiver risk.

## Information Architecture

### Persistent Header

The header remains visible above the tabs and contains:

- back link to all students;
- student avatar/initials;
- student name;
- status chip;
- age and DOB;
- level or skill level;
- parent name, email, and phone;
- compact status strip:
  - current due;
  - dues status;
  - attendance rate;
  - last attended;
  - active session count;
  - waiver status.

The header should be dense but not cramped. It is an admin operations surface,
not a marketing or coach mobile page.

### Overview Tab

Purpose: fast admin snapshot and safe profile editing.

Content:

- editable full name;
- editable DOB;
- editable level/skill level;
- editable status;
- editable internal notes;
- parent contact summary;
- warning rows for:
  - overdue or due payment;
  - missing waiver;
  - missing emergency contact;
  - no active session;
  - low attendance when data exists.

Primary behavior:

- admins can edit safe profile basics directly;
- save uses a visible dirty state and audit reason;
- discard resets unsaved edits;
- loading, error, and empty states remain explicit.

### Training Tab

Purpose: student development and safety context for admins.

Content:

- editable skill level;
- editable previous experience;
- editable medical notes;
- editable emergency contact name;
- editable emergency contact phone;
- attendance rate;
- last attended date;
- recent attendance rows after the BFF exposes them.

This tab should avoid becoming a coach-in-class screen. It is for admins to know
the student's context and spot operational risk.

### Sessions Tab

Purpose: enrollment and schedule management.

Content:

- active enrolled sessions;
- session title;
- location;
- start/end schedule;
- enrollment status;
- billing mode;
- subscription status;
- session price;
- move session action.

Behavior:

- session rows are mostly read-only;
- move session opens a guided action requiring target session, effective date,
  and reason;
- move history is not shown in the first implementation.

### Billing Tab

Purpose: payment visibility without duplicating billing ownership.

Content:

- current due amount;
- current period;
- payment or invoice id;
- linked session;
- payment history table:
  - date;
  - period;
  - amount;
  - paid amount;
  - balance;
  - method;
  - status.

Behavior:

- billing data is read-only on the profile;
- deeper billing edits should link to the admin billing workflow;
- the profile may expose quick navigation such as "View billing record" but
  should not introduce freeform billing mutation fields.

### Family & Compliance Tab

Purpose: parent account ownership, waiver state, and admin safety checks.

Content:

- parent account details;
- parent email and phone;
- change parent action;
- waiver accepted status;
- waiver accepted date/version when available;
- editable T-shirt size for academy operations;
- relevant audit/event history for:
  - profile edits;
  - parent changes;
  - session moves.

Behavior:

- parent changes are guarded and require confirmation plus reason;
- waiver status is read-only unless a separate approved override workflow exists;
- historical billing, waiver, credit, and waitlist rows should not be silently
  rewritten during parent change.

## Edit Model

### Directly Editable Fields

Admins can edit:

- full name;
- date of birth;
- level or skill level;
- status;
- internal notes;
- previous experience;
- medical notes;
- emergency contact name;
- emergency contact phone;
- T-shirt size.

### Guarded Actions

The following actions use dialogs or guided flows:

- **Move session:** target session, effective date, reason.
- **Change parent:** new parent, confirmation, reason, impact warning.
- **Billing changes:** route to billing workflows.
- **Waiver override:** out of scope for this redesign.

### Save Behavior

Use a per-tab dirty state with a sticky save/discard bar when fields change.

Each save sends only the changed profile fields and an audit reason. The default
reason can be "Admin profile update", but the UI should allow admins to change
it before saving. Guarded actions collect their own reasons.

## Backend / BFF Shape

Keep the frontend presentation-focused. The BFF should provide normalized,
already-authorized admin data.

Recommended additions or normalizations to `AdminStudentDetailView`:

- normalize `level` from `level || skill_level` so the frontend has one display
  and edit field;
- `previous_experience: str | None`;
- `medical_notes: str | None`;
- `emergency_contact_name: str | None`;
- `emergency_contact_phone: str | None`;
- `t_shirt_size: str | None`;
- `waiver_status: "signed" | "missing" | "unknown"`;
- `waiver_signed_at: datetime | None`;
- `waiver_version: str | None`;
- `recent_attendance: list` limited to the latest 10 attendance rows.

The frontend can derive age from `date_of_birth`. Do not add a separate age
field unless the backend later needs academy-specific age rules.

Move history is not required for the first implementation.

Recommended update request additions:

- `level`;
- `previous_experience`;
- `medical_notes`;
- `emergency_contact_name`;
- `emergency_contact_phone`;
- `t_shirt_size`.

Backend should keep tenant scoping and audit behavior in the v2 admin BFF and
enrollment context. The frontend should not infer tenant or calculate business
truth beyond display formatting.

## Frontend Components

The current page can remain the route owner, but the redesign should split the
large page into focused components:

- `StudentProfileHeader`
- `StudentProfileTabs`
- `StudentOverviewTab`
- `StudentTrainingTab`
- `StudentSessionsTab`
- `StudentBillingTab`
- `StudentFamilyComplianceTab`
- `StudentDirtySaveBar`
- `MoveStudentSessionDialog`
- `ChangeStudentParentPanel` or dialog

Use existing design-system components where possible:

- `Card`
- `Button`
- `Chip`
- `Avatar`
- `Overline`

The UI should remain desktop-first and mobile-tolerant, matching the admin
control-plane direction.

## Error Handling

Required states:

- skeleton loading state matching the tabbed layout;
- student not found state;
- API error state with retry;
- save error state near the save bar;
- validation errors below the relevant fields;
- guarded action errors inside the dialog;
- empty states for no sessions, no payments, no attendance rows, and no waiver.

## Risks

- Adding too much data to the profile can make it slower and harder to scan.
  The persistent header and tabs reduce this risk.
- Billing mutations on the profile could bypass billing rules. Keep billing
  edits in billing workflows.
- Parent changes can affect historical records. Keep the existing warning and
  audit behavior.
- Skill level may remain blank if `skill_level` is not normalized into the BFF
  detail response.
- Waiver and attendance additions may require new repository joins or separate
  BFF queries. Keep the first implementation bounded.

## Verification Plan

Focused verification should include:

- frontend typecheck;
- admin student E2E coverage for loading profile, switching tabs, editing safe
  fields, saving with reason, and seeing updated values;
- E2E or component coverage for guarded move-session and change-parent dialogs;
- backend application/interface tests for added fields and update request
  forwarding;
- Mongo repository contract tests for normalized `level`/`skill_level`,
  emergency contact fields, medical notes, waiver fields, and tenant isolation;
- mobile-tolerant screenshot or Playwright viewport check for the tabbed layout.

## Out Of Scope

- coach mobile in-class profile redesign;
- freeform billing edits on the student profile;
- production deploy;
- rewriting legacy routes;
- changing SaaS tenant resolution.
