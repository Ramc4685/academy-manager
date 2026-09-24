# People reports: money owed by age and inquiries by source

PR: #949

## What changed
- `/admin/reports` gains a "People" group with two cards, both plain tables with empty states.
- Money owed by age: open balance split into not yet due, 1 to 30, 31 to 60 and over 60 days late, with the family count and total per band (`GET /api/v2/admin/reports/people/money-owed-by-age`). It reads billing's existing family money rule, so its totals match the Families view to the cent. Roles that may not see family money (`can_view_family_money`) get 403 and the card is hidden.
- Inquiries to enrolled by source: `crm_contacts` counted by source and pipeline status over academy-local dates, default the last 90 days (`GET /api/v2/admin/reports/people/inquiry-conversion?from=&to=`).

## Deploy notes
- None. No migrations (the inquiry count uses the existing `crm_contacts_academy_created` index from 0192), no env vars, no owner steps. Read-only.

## Risk / rollback
- The money card makes three reads of billing's family money model per request (today, -30, -60); fine at current size, a single-read port is a follow-up.
- Low: two new read-only admin routes and two cards. A wrong number is a display problem only; nothing writes.
- Rollback: revert this PR and redeploy backend and frontend.
