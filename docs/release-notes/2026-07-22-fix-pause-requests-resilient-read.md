# fix-pause-requests-resilient-read

PR: #325

## What changed
`GET /api/v2/admin/pause-requests` (and the parent pause list) no longer 500s
when a single stored `pause_requests` document violates the `PauseRequest`
pause-window invariant — for example a legacy row with neither `pause_kind` nor
`resume_on`, a shape the Mongo `$jsonSchema` from migration 0133 still permits.
`MongoPauseRequestRepository._to_domain()` rebuilt the aggregate straight from
each document, so the model re-ran its write-time `_validate_pause_window`
check on every read and one bad row took down the whole list.

`_to_domain` now catches that validation failure, logs a warning, and coerces
the row into a valid indefinite pause (review date derived from the document's
period or `created_at`) so it still renders and admins can approve or decline
it — nothing is silently dropped. `get` and the parent list share the same
reconstruction and are fixed by the same change. The write path is untouched:
`RequestEnrollmentPauseCommand` still enforces the invariant on create.

Also bumps `pyasn1` 0.6.3 → 0.6.4 (transitive, via `google-auth`) to clear
PYSEC-2026-3455/3456/3457, which `pip-audit` fails the backend job on.

## Deploy notes
none — no migrations, no env changes, no data backfill. Legacy rows are
repaired in memory on read only; the stored documents are left as-is.

## Risk / rollback
Low. The coercion only applies to documents that would otherwise raise, so
well-formed pause requests reconstruct exactly as before. A coerced row is
presented as an indefinite pause, which is the more conservative reading of a
document with no resume date — an admin still has to act on it explicitly.
Rollback is a pure code revert; nothing is written differently.
