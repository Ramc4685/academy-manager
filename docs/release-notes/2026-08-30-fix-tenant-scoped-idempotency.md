# tenant-scoped-idempotency

PR: #569

## What changed
Attendance idempotency keys were built solely from the raw client-supplied
`mutation_id` (`mark_attendance:{mutation_id}`), and the shared
`idempotency_keys` collection is global. An authenticated coach in academy B
could replay a `mutation_id` already used in academy A and receive academy A's
cached `MarkAttendanceResult` (leaking A's student/occurrence/session IDs
across tenants) while B's own write was silently skipped; the same replay let
any coach pre-claim another coach's pending offline-sync mutation. Both
`MarkAttendance` and `BulkMarkAttendance` keys now embed server-derived scope
— `mark_attendance:{academy_id}:{coach_id}:{mutation_id}` — and the coach BFF
request models constrain `mutation_id` to a 26-char Crockford-base32 ULID
(the format the frontend offline queue already generates), since it also
becomes the attendance primary key.

## Deploy notes
None beyond the normal deploy. No migration: the existing global
`idempotency_keys` collection and TTL index are unchanged — only the key
strings written to it gain a scope prefix.

## Risk / rollback
Keys cached under the old unscoped format stop matching after deploy, so a
mutation executed pre-deploy and replayed post-deploy (within the 7-day TTL)
re-executes instead of hitting the cache; attendance writes are keyed by
`attendance_id = mutation_id`, so the replay converges on the same row rather
than duplicating. Clients sending a non-ULID `mutation_id` now get a 422 —
the shipped frontend generates real ULIDs via `ulid()`, so only hand-rolled
callers are affected. Roll back by reverting the merge commit; no stored
state depends on the new key shape.
