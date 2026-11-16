# coach-attendance

PR: TBD

## What changed
Coaches can now change a mark for 48 hours, as the screen already said. They cannot mark a class more than an hour before it starts, mark Late from the class screen, or undo an admin void. Marks that fail to send stay queued and retry on their own. A replayed mark or batch never ends up in Needs review against its own saved rows, a different-status conflict offers "Keep" or "Change to", and signing out clears the device's queue and cached coach data.

## Deploy notes
None. No migration, env var or index change. Two coaching events that had no handler (`AttendanceVoided`, `SessionFeedbackPosted`) are now audit-only, so they stop landing in dead letters.

## Risk / rollback
The new one-hour lead-time check rejects marks sent earlier than that with `409 OccurrenceNotStarted`. Bulk marks are capped at 100 entries per request. Past class rosters now leave out children who joined after the class, and they keep marked children who have since left. Roll back by reverting the merge commit; no data needs undoing.
