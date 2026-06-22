# Enrollment Billing Deferrals

Monthly invoice generation must not rely on `enrollment.status == "paused"` or
`enrollments.skip_periods` as silent billing exclusion truth.

## Current Rule

New pause-related billing deferrals are recorded in
`enrollment_billing_deferrals`. Active deferrals include:

- `enrollment_id`
- `student_id`
- `deferral_type`
- `reason`
- `source` and optional `source_id`
- `actor_id` / `actor_type`
- `billing_period`
- `created_at`
- one of `resume_on`, `review_on`, or `expires_on`

Fixed parent pauses create a `fixed_pause` deferral and a scheduled resume
action. Indefinite parent pauses require `review_on` and create a reviewable
deferral. Direct admin pauses require either `resume_on` or `review_on`.

## Monthly Billing

`POST /api/v2/admin/payments/generate-monthly` skips an enrollment only when an
active deferral covers the requested billing period, or when legacy
`skip_periods` compatibility applies. The response keeps aggregate counters and
adds `skipped_details` with enrollment, student, reason, source, period, and
resume/review/expiry metadata.

Expired or out-of-period deferrals do not suppress monthly invoice generation.

## Legacy `skip_periods`

Existing `skip_periods` data is not deleted or backfilled by startup migration.
When monthly generation sees a matching legacy skip without a deferral record,
it emits a row-level `legacy_skip_period` skipped detail with `needs_review`.
Admin attention also flags legacy skip metadata for cleanup.

No production backfill is required for this change. If cleanup is needed later,
run it as an explicit operator-approved backfill that creates deferral records
from auditable pause request history and leaves the original array intact until
verified.
