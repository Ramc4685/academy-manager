# Birthdays and profile nudges — design

Date: 2026-09-10. Owner decisions from the brainstorming session are recorded inline.
Third of four specs from the 2026-09-10 admin-UX session. Builds on
`2026-07-29-parent-profile-completion-design.md`, which defined the required-field set,
the shared `ProfileGaps` rule, the parent profile page and banner, and explicitly deferred
email reminders. This spec adds the emails.

## 1. Purpose

Two things the academy wants to do with data it already collects:

1. Wish every child a happy birthday — every child on file, not only the ones in a class
   this month.
2. Get the missing details (date of birth first, then emergency contact, medical answer,
   parent phone) filled in without an admin chasing each family by hand.

Verified facts: `Student.date_of_birth` is a free-form string, present on the student
document regardless of enrollment status (withdrawal changes `Enrollment.status`, never
deletes the student). Nothing reads DOB except the edit forms and `ProfileGaps`. The
scheduler in `main.py` already runs daily and weekly jobs (hold reminders, coach digests,
dunning), emails go through the communications context with categories and an
unsubscribe footer (`email_preferences`, migration 0159).

## 2. Owner decisions

| Question | Decision |
|---|---|
| Who gets a birthday note | Students only. Parents' birthdays are not collected or celebrated. |
| Which students | Every student with a DOB, any status. Active/held/paused students' families get the automated email; withdrawn/dropped students appear on the staff digest only, so a human decides. |
| Never-enrolled siblings | Out of scope: no student record, no birthday. |
| Nudge cadence | Three bundled emails per family — day 7, 21 and 60 after the gap is first seen — then stop. Stops early when the gap closes. |
| Nudge channel | Email to the parent (plus the existing in-app banner). |
| Consent | Owner to confirm the registration wording covers birthday emails as a use of the child's DOB before the automated email is switched on; the staff digest needs no new consent. |

## 3. Data

- `students.date_of_birth` stays a string but is validated as `YYYY-MM-DD` on every
  write path (admin form, parent profile, onboarding) — today only the onboarding DTO
  checks format.
- New derived field `students.birth_month_day` (`"MM-DD"`), written whenever
  `date_of_birth` is set, indexed `(academy_id, birth_month_day)`. Migration backfills it
  from parseable DOBs and reports the unparseable ones (they count as a DOB gap).
- New collection `profile_nudges`: `(academy_id, parent_id)` → `first_gap_seen_at`,
  `sends: [{at, step, fields}]`, `closed_at`. Unique on `(academy_id, parent_id)`.
- Birthday sends claim through the existing `digest_claim` with key
  `(academy_id, student_id, year)` so a job re-run can never send twice.

## 4. Birthday outreach

### 4.1 Staff digest (always on)

A "Birthdays this week" block in the existing coach daily digest on Mondays and in the
admin ops digest: student name, age turning, day, class(es) or "not enrolled", parent
name. Withdrawn students are listed with a "left on <date>" note. Coaches see only their
classes' students; admins/owners see all.

### 4.2 Family email (switchable)

Job `send_birthday_notes`, daily, academy-local morning. Selects students where
`birth_month_day` = today, `is_deleted` false, with at least one enrollment in
`active|held|paused`, parent has an email and has not unsubscribed from NOTIFICATION
mail. One email per student ("Happy birthday, Aanya!"), academy-branded, no call to
action, unsubscribe footer. Per-academy setting `birthday_emails_enabled` (default off)
beside the enrollment policy in settings; the owner turns it on after the consent check.

## 5. Profile nudges

Job `send_profile_nudges`, daily. For each parent with at least one active/held/paused
student: compute `ProfileGaps`; if empty, close any open nudge record and continue. If
gaps exist and no record, create one with `first_gap_seen_at = now` and send step 1 if
`first_gap_seen_at` is older than 7 days (so a brand-new family is not nudged the day
they register). Steps: 1 at day 7, 2 at day 21 from step 1, 3 at day 60 from step 2. No
step 4.

One email per parent per step listing every missing field across all children, with a
deep link to `/parent/profile`. Category NOTIFICATION, unsubscribe honoured. Copy
explains why each field matters (DOB → birthday and age-group placement; emergency
contact → safety).

Admin visibility: the Families list "Needs attention" sort (spec 2) includes "profile
incomplete" and shows the last nudge date; the existing `missing=` filter on the students
list is unchanged.

## 6. Out of scope

- Parent birthdays; never-enrolled siblings; SMS/WhatsApp nudges.
- Age-group auto-placement from DOB (later, once DOBs are clean).
- Any change to the parent profile page or banner.

## 7. Testing

- Unit: `birth_month_day` derivation incl. leap day (Feb 29 → listed Feb 28 in non-leap
  years); nudge step scheduling table; gap-closes-stops-nudging.
- Backend: jobs are idempotent under re-run (claim/record prevents double send);
  unsubscribed parent receives nothing; withdrawn-only student is in the digest, not the
  email; setting off → no family email.
- Migration test: backfill parses `YYYY-MM-DD`, skips and reports others.
