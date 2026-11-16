# admin-numbers-and-pickers

PR: #1176

## What changed
Admin counts follow the owner rules: Overdue counts families past the due date in any month (not only the current one) without autopay cover, at risk means two recorded absences in a row, "today" is the academy's day, the inbox badge counts only decisions, and a count that fails to load says so instead of showing 0. Student pickers search the whole academy on the server, the Sessions page can list every class, including ended and far-future ones, and the reports dashboard ages balances against today and counts classes in every month they meet.

## Deploy notes
None. No migration, env var or config change. The response models gain optional fields (`unavailable`, `phase`, `latest_event_type`, `latest_event_date`), which older clients ignore, and `GET /admin/payments/overdue-families` is new. It reads the existing `academy_invoice_status_due_date` index (0156).

## Risk / rollback
Medium-low. Read paths and admin UI only; nothing writes money or enrollment state. The at-risk count will drop in production because the old rule flagged any student with no recent attendance. Roll back by reverting the PR.
