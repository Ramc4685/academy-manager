# audit-only-events-not-dead-lettered

PR: #1062

## What changed
Events published only as an audit record (attendance marked/corrected, autopay consent, waitlist promoted, skill status, subscription updated) are now marked processed instead of dead-lettered, so the daily ops digest stops flagging "attention needed" whenever a coach marks attendance. Unknown events still dead-letter. The invoice-generation summary in the digest now also shows `invoice_autopay_notices_sent`, so a run that notified autopay parents no longer reads as "0 emailed".

## Deploy notes
None. The ~436 existing `unregistered_schema_version` rows for these events stay in `dead_letter_events` (all-time count unchanged) until cleaned up separately.

## Risk / rollback
If one of these events was meant to have a consumer, it is now marked processed silently rather than parked for replay; registering a handler for it still takes priority. Roll back by reverting the PR.
