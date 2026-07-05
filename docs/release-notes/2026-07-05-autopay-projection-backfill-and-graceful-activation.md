# autopay-projection-backfill-and-graceful-activation

PR: #286

## What changed
Follow-up to the 2026-07-04 prod incident: `student_billing_enrollments`
(the autopay-state projection) was empty for enrollments created by the
legacy flow, so `CompleteAutopaySetup` raised an unhandled `RuntimeError`
and 500'd the checkout-status poll — parents got stuck on "Confirming
autopay…". A one-off manual backfill (52 docs) was already applied in prod;
this PR makes that fix durable and adds guardrails:

- Migration `0145_backfill_student_billing_enrollments` — idempotent,
  insert-only backfill from legacy `enrollments` for every environment.
- Self-heal in `mark_autopay_active_from_setup` — auto-creates the missing
  projection doc from the legacy enrollment before activating, so any
  enrollment the migration missed still activates instead of erroring.
- New `AutopayActivationFailed` (409) domain error replaces the raw 500.
- Audited admin toggle for `allow_platform_charge_fallback`
  (`GET`/`PUT /api/v2/admin/billing/settings/platform-fallback`) — previously
  only settable via a manual Mongo write; now writes an audit entry before
  the settings change.

## Deploy notes
Includes migration `0145_backfill_student_billing_enrollments`.
`V2_RUN_MIGRATIONS_ON_BOOT=true` is set in `backend/fly.toml`, so the
migration runs automatically on backend boot after deploy — no manual step
needed. Confirm it ran via the migration log / `student_billing_enrollments`
doc count after deploy as a sanity check.

## Risk / rollback
Migration is insert-only (`$setOnInsert`) and safe to re-run; it never
touches existing projection docs. If activation behavior regresses, revert
the merge commit — the self-heal and migration are both additive and don't
change any existing autopay state.
