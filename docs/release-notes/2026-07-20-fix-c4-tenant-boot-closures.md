# fix-c4-tenant-boot-closures

PR: #TBD

## What changed
Parent read paths and coach/parent write use cases no longer bind `academy_id`
at process boot. Inline parent reads (`list_payments/children/enrollments/
attendance/progress`, invoice detail, autopay/balance checkout ownership
checks, billing portal) resolve the tenant per request via `current_academy_id()`;
`MarkAttendance`, `BulkMarkAttendance`, `CoachAddStudentToRoster`,
`ConfirmEnrollment`, `PromoteFromWaitlist`, `AcceptParentWaiver`, and
`StartApplication` now take a request-time tenant provider with a boot-value
fallback. Per-path tenant-isolation tests added (audit item C4).

## Deploy notes
none — no migrations, no env changes. Single-academy behavior is unchanged
(tenancy middleware pins the primary academy; the provider falls back to the
boot value for non-HTTP callers such as outbox handlers).

## Risk / rollback
If a converted path ever runs without tenant context, inline reads raise
`TenantContextUnset` instead of silently using the boot academy (fail-closed);
use-case writes fall back to the boot academy. Rollback is a pure code revert —
no data is written differently in single-academy production.
