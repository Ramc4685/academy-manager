# fix-session-edit-save-cache

PR: #372

## What changed
Admin session edits now apply the saved API response to the Sessions list and
session detail caches immediately, so updated schedule, capacity, coach, and
monthly fee values remain visible after saving.

## Deploy notes
None.

## Risk / rollback
Low frontend-only cache update. Roll back by reverting the session edit cache
write if the Sessions list or detail view shows incorrect post-save data.
