# admin-numbers-and-pickers

PR: TBD

## What changed
- Admin student pickers (Add to roster, Record absence) search the whole academy on the server, putting students who are still enrolled first. They used to load the first 50 students alphabetically, so anyone later in the alphabet could not be picked.
- Dashboard "Overdue dues" counts families past the due date without autopay, from the same collections view as Payments. Drafts and not-yet-due invoices no longer count.
- "At risk" now means two recorded absences in a row on a live seat. New students, unmarked classes and voided marks no longer make a student at risk.
- Admin "today" and "this month" (dashboard, date defaults in payment, expense, payout, enrollment and invoice dialogs) use the academy's timezone, not UTC. An evening in Chicago no longer reads as tomorrow.
- Inbox badge counts only items that need an admin decision. Absence notices and cancellations stay visible on their tabs but no longer count.
- A dashboard card or inbox count that fails to load shows "Could not check" or "?" instead of a silent 0.
- Students page "Payment risk" tile shows the academy-wide count of families past due or with failed autopay and links to Payments. It used to count only the rows on screen.
- Sessions page has an "All classes" view with text and status filters, so classes beyond the next 30 days or already ended can be found. A sessions-list date now means the academy-local day. The global waitlist covers every class that has not ended, not only the next 30 days.
- Reports dashboard: the collections aging buckets age unpaid balances against today (academy time), not the month end, so a not-yet-due invoice reads Current and an old balance reaches 31-60 or 60+. Sessions, capacity and waitlist count every class that meets in the month, not only classes that began in it.
- The class roster shows each seat's latest lifecycle event from the roster response instead of one request per row. Roster student and parent lookups now use the request's academy.

## Deploy notes
None. No migration, env var or config change. The response models gain optional fields (`unavailable`, `phase`, `latest_event_type`, `latest_event_date`), which older clients ignore.

## Risk / rollback
Medium-low. Read paths and admin UI only; nothing writes money or enrollment state. The at-risk count will drop in production because the old rule flagged any student with no recent attendance. Roll back by reverting the PR.
