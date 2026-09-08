# month-close

PR: #687

## What changed
The admin Reports page becomes **Month close**, reframed around the two monthly runs: what invoice generation produced (generated, emailed, autopay notices, voided with reasons), the money (billed, collected, outstanding, collection rate), the autopay run for the period, and an "anything odd" box. `cash_received_in_period` is now the single definition of cash received, replacing several disagreeing computations; the dead `/admin/reports/kpis` route is deleted. The Dues page is retired — both bookmarks redirect to Payments, its WhatsApp link moves onto the Past due and Awaiting bucket rows, and its tuition-discount card moves to Month close. The failed-autopay card, the recent-payments feed and three CSV exports are removed.

## Deploy notes
No migration, no data change, no env. Routes removed: `GET /admin/reports/kpis` and `GET /admin/dues-followup` (the `list_dues_followup` composition closure stays — the dashboard attention card reads it). CSV exports removed: pending-payments, revenue, attendance; QuickBooks and deposit slip remain. `/admin/reports/dues` and `/admin/dues` now redirect to `/admin/payments`.

## Risk / rollback
The deposit slip and QuickBooks journal are deliberately unchanged: their gross is computed differently from the new cash reader (per-row amount and legacy-payment membership both differ), so unifying them would alter book-keeping output and needs its own PR. The emailed vs autopay-notice split is re-derived from each enrollment's current autopay status because the message kind is not persisted — the two counts can move between each other if autopay changed after the send, though their sum is always the true sent count. Rollback by reverting; nothing stored changes shape.
