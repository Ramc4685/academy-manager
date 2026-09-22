# batch-11b: registration class visibility

PR: #0

## What changed
- Fixes #891 — Admin registration queue rows now name the class each family asked for, in both the desktop table and the phone card layout. `list_pending()` resolves each distinct `selected_session_id` once per page (mirroring the existing one-read-per-page rule the waiver template already follows), and `session_title` moved up from `AdminRegistrationDetail` onto the shared `AdminRegistrationRow` / `AdminRegistrationRowView` base. The desktop table gains a Class column after Student; the phone row gains a class line in its secondary block.
- Fixes #891 — Rows an admin can act on today (`PENDING_APPROVAL`) now render first, with `MANUAL_REVIEW` and stale review claims grouped behind a "Needs another look" heading. This is a UI-only split of the existing `status` field on the row; no new derivation was added. Phone "direct Review" (row title as the review link) was already satisfied by #857 and is now pinned by a regression assertion rather than new UI.

## Deploy notes
No migration required. `admin.py` was not touched. The change is confined to `list_pending()`'s DTO assembly and the admin registration queue view components; no new backend endpoints, indexes, or config/env vars are introduced.

## Risk / rollback
Risk is limited to the admin registration queue read path: an extra per-page resolution of `selected_session_id` to a class title, and a client-side grouping of rows by status. Both are additive and covered by unit/interface tests exercising `list_pending()` and the queue view. If this regresses, revert this PR (no data migration to unwind).
