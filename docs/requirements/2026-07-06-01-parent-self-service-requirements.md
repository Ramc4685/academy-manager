# Parent Self-Service: Absence/Makeup, Trial Requests, Self-Cancel — Requirements

Date: 2026-07-06 · Roadmap item 5 of 9 · [Index](2026-07-06-00-roadmap-index.md)

## Problem

Every incumbent studied lets parents self-serve requests that currently require a
phone call to us: Jackrabbit supports flexible absence/makeup workflows; iClassPro
lets parents submit drop/transfer requests and trial-class requests directly from
the Customer Portal; CourtReserve's *lack* of self-serve cancel is an explicit,
named review complaint ("members cannot self-serve cancel/change a reservation
without calling/texting the admin"). We currently have none of these three flows —
parent-initiated absence/makeup requests, trial-class requests, or self-cancel of an
enrollment/booking.

## Current State (codebase evidence)

- `backend/v2/contexts/enrollment/` — `Session`, `SessionOccurrence` exist with
  status tracking (scheduled/cancelled/completed) and coach/substitute assignment,
  but there is no "student requested absence" or "makeup session" concept.
- `backend/v2/contexts/onboarding/` — `Application`, `StartApplication`,
  `PatchApplication`, `GetApplicationStatus` handle the *initial* registration
  application, with admin `ApproveRegistration` / `RejectRegistration` /
  `WaitlistRegistration`. There is no "trial class request" concept distinct from a
  full application.
- No self-cancel exists anywhere in the parent-facing API — a parent cannot cancel
  their own enrollment or a single upcoming occurrence; only admin actions
  (`ApproveRegistration` etc.) mutate enrollment state today.
- Coach attendance marking (`backend/v2/interfaces/coach/attendance_routes.py`)
  records attendance after the fact; it has no upstream "parent said they'd be
  absent" signal to reconcile against.

## Goals

- Parent can submit an absence notice for an upcoming session occurrence, ahead of
  time, from the parent portal.
- Parent can request a makeup for a missed/absent session, subject to admin-
  configured makeup rules (capacity, eligible session types, expiry window).
- Parent can request a trial class for a prospective or existing student without
  going through the full paid-application flow.
- Parent can self-cancel their own enrollment (or a specific upcoming booking, if
  the academy supports single-session bookings), subject to admin-configured
  cancellation policy (notice period, fee).

## Non-Goals

- No change to coach-side attendance marking mechanics — this is parent-initiated
  requests that admins/coaches review, not a replacement for attendance recording.
- No refund-automation logic beyond what already exists in `CreditLedgerEntry` —
  self-cancel triggers existing credit/refund machinery, doesn't reinvent it.

## Requirements

### R1. Absence notice
- Parent submits an `AbsenceNotice` for a specific `SessionOccurrence`, before the
  session starts (enforce a minimum notice window, admin-configurable per academy,
  default e.g. 2 hours).
- Coach/admin sees pre-flagged absences on the roster/attendance view before
  marking attendance, distinct from an unexplained no-show.
- Absence notice does not itself grant a makeup — that's a separate, admin/coach-
  reviewed request (R2), since not every academy's policy grants automatic makeups.

### R2. Makeup request
- Parent requests a makeup for a specific missed/absent occurrence, selecting from
  a list of eligible upcoming occurrences (same or compatible session type/level,
  capacity available, within an admin-configured expiry window from the missed
  date — e.g., 30 days).
- Admin/coach approves or denies; approval creates a one-time enrollment/roster
  entry on the target occurrence without generating a new billing charge (the
  student already paid for the missed session).
- Makeup credit expires if unused within the configured window; expired credits
  are visible to admin and parent, not silently dropped.

### R3. Trial class request
- Parent (existing or prospective, i.e., before full application/approval) submits
  a `TrialRequest`: desired session/program, preferred date range, child info if
  prospective.
- Admin approves/denies and assigns a specific occurrence; approval creates a
  no-charge (or admin-configured trial-fee) roster entry for that single occurrence.
- If the prospective family proceeds to full enrollment after the trial, the trial
  request links to the resulting `Application`/enrollment for continuity/reporting
  (conversion tracking).

### R4. Self-cancel
- Parent can cancel their own enrollment (ends future billing, per existing
  proration/credit logic) subject to an admin-configured cancellation policy:
  minimum notice period, whether a cancellation fee applies, and whether it's
  immediate or effective at period end.
- Self-cancel of a single upcoming occurrence (not full enrollment) is supported if
  the academy's enrollment model allows single-session drop-in bookings — flag as
  in-scope only if drop-in/single-session bookings exist by the time this ships
  (see dependency on any drop-in/pack feature, currently unscoped).
- Cancellation always produces an auditable record (who cancelled, when, policy
  applied, resulting refund/credit if any) — never a silent state change.

## Data Model Changes

### New `absence_notices`
```text
notice_id
academy_id
student_id
session_occurrence_id
submitted_by: parent_id
submitted_at
notice_window_met: bool
```

### New `makeup_requests`
```text
request_id
academy_id
student_id
missed_occurrence_id
requested_target_occurrence_id: string | null   # null until admin assigns
status: "pending" | "approved" | "denied" | "expired" | "completed"
expires_at
decided_by: admin_user_id | null
decided_at
```

### New `trial_requests`
```text
request_id
academy_id
prospective_or_student_ref: { type: "prospective"|"existing_student", ... }
requested_program_id
preferred_date_range
status: "pending" | "approved" | "denied" | "completed" | "converted"
assigned_occurrence_id: string | null
linked_application_id: string | null   # set if converted to full enrollment
```

### New `self_cancellation_policies` (per academy)
```text
policy_id
academy_id
minimum_notice_days
cancellation_fee_cents: int
effective_timing: "immediate" | "end_of_period"
```

### `enrollment` (extend)
```text
cancelled_by: "admin" | "parent" | null
cancellation_reason: string | null
cancellation_policy_applied: policy_id | null
```

## Dependencies

- None on other roadmap items. Can be built in parallel with the billing track.
- If single-session self-cancel is scoped, confirm whether a drop-in/pack booking
  model exists — if not, defer that sub-case and ship full-enrollment self-cancel
  first.

## Open Decisions

1. Does a missed session with no absence notice (unexplained no-show) ever qualify
   for a makeup, or only pre-notified absences? (Recommendation: admin-configurable
   per academy, default = notified absences only.)
2. Is trial-class capacity separate from regular enrollment capacity, or does a
   trial consume a normal roster slot?
3. Cancellation fee: flat amount, percentage of remaining term, or admin discretion
   per request?
4. Should makeup requests auto-approve if the target occurrence has open capacity
   and meets eligibility rules, or always require a human review step? (Market
   precedent: iClassPro's Autopilot automates the notify/approve waitlist flow —
   consider the same for makeups once trust in the rule engine is established.)

## Acceptance Criteria / Test Cases

- Parent submits an absence notice ≥2 hours before a session; coach's roster view
  shows the student pre-flagged as an expected absence, not an unexplained no-show.
- Parent requests a makeup for a properly-noticed absence; admin approves; the
  student is rostered on the target occurrence with no new invoice line generated.
- An approved makeup request that goes unused past its expiry window is marked
  `expired` and is visible to both parent and admin (not silently lost).
- Prospective family submits a trial request, is approved for a specific
  occurrence, attends, then enrolls — the resulting application links back to the
  original trial request for conversion reporting.
- Parent self-cancels an enrollment with sufficient notice; no cancellation fee is
  applied per policy; enrollment billing stops at the configured effective timing.
- Parent self-cancels with insufficient notice; the configured cancellation fee
  appears as a distinct, auditable invoice line.
