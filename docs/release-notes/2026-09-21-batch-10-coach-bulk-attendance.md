# batch-10: coach bulk attendance

PR: #868

## What changed
- Fixes #866 — "Mark rest present (N)" on the coach session roster now pre-filters
  the count so it stops promising a number the bulk-attendance endpoint will refuse.
  Two lifecycle facts already shown on the roster are excluded from the batch:
  an on-hold/reclaim-pending enrollment (the "ON HOLD" chip, #697/#773) and a row
  with a parent-submitted absence notice for that occurrence. Previously the count
  included both, the bulk endpoint rejected the whole batch with
  `Coaching.BulkStudentNotEnrolled` (#672), and only the retry after that 422
  excluded them.
- This is a client-side pre-filter only: the delayed-save/undo window (#846), the
  queue contract, request payloads, and the post-rejection `ineligibleIds` retry
  path are all untouched. The server remains the authority for anything the client
  cannot predict (e.g. a paused seat, or a hold placed after the roster was
  fetched). Both excluded row types stay individually tappable; only the bulk
  "mark rest present" batch skips them.

## Deploy notes
No migration. Frontend-only change (`frontend/lib/coach/bulk-eligibility.ts` and
`frontend/app/(coach)/coach/sessions/[id]/page.tsx`); no manual env var or manual
step is needed before merge.

## Risk / rollback
Low risk: this narrows an existing bulk-mark count using data already rendered on
the roster, and does not change what the server accepts or rejects. Worst case is
the count under- or over-counts by one lifecycle case; the existing post-rejection
retry path is unchanged and still recovers from any bulk-endpoint rejection. Revert
this PR (or the merge commit) to roll back.
