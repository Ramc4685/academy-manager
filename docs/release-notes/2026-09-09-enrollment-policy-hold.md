# enrollment-policy-hold

PR: #701

## What changed

Pause becomes a hold that keeps the child's seat instead of releasing it, bounded by a configurable maximum (default 60 days) and requiring a return date. When a full class needs a seat, the longest-held hold is reclaimed automatically, that enrollment is dropped and the family is emailed the reason. A reminder email goes out monthly while a hold runs. A new per-academy departure policy in admin settings holds the default drop outcome (default: no credit, mid-month), who may delete an enrollment (default: owner), the maximum hold length and the reclaim rule.

## Deploy notes

New collection for the departure policy; defaults apply with no row present. Three new scheduled jobs are registered: hold expiry (daily 02:45), hold reminders (daily 04:00) and stalled reclaim recovery (every 15 minutes), each with matching ops-digest staleness entries. No data migration.

## Risk / rollback

The seat counter only ever increments, so reclaim is the double-booking risk; every release is judged on a compare-and-set pre-image against the seat-holding status set, with property and wiring tests. Four known gaps are listed in the PR body. Rollback by reverting.
