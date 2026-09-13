# Batch 4: Leaving Report Removed Event

## What changed
- Fixes #744 — the leaving report never showed enrollments that were removed via the Delete-enrollment route (`DELETE /enrollments/{id}`). That route records a lifecycle event with `event_type` `"removed"`, but the leaving report's `DEPARTURE_EVENT_TYPES` frozenset filter didn't include that value, so those rows silently dropped out of the report.
- Added `"removed"` to `DEPARTURE_EVENT_TYPES` and corrected the stale comment above it, which incorrectly attributed Delete's event type to `"dropped"`/`"deleted"`.
- Added a new test file covering both the direct set-membership regression (`"removed"` is in `DEPARTURE_EVENT_TYPES`) and an end-to-end leaving-report row for a `"removed"` event with reason "Removed by admin".

## Deploy notes
No migrations. No manual steps. This only widens a filter set used when building the leaving report; no schema or data changes.

## Risk / rollback
Low risk — the change adds one value to a filter frozenset used for read-only reporting. No other code paths depend on `DEPARTURE_EVENT_TYPES`. Rollback: revert this PR.

PR: #793
