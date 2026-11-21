# Email campaign audiences, invoice digest counts and waiver invoices

PR: TBD

## What changed
- Email campaign count (#1029): the composer's count comes from the server, not a client estimate. A new `POST /admin/campaigns/preview` resolves the audience the send would reach and emails nobody. Siblings share one family email, so it reads like "7 email recipients on Sat Beginners (7 families + 1 family contact)". The count shows no number while it loads or if it fails.
- Recipient review (#1031): before sending, the admin sees who will get the email and who will not, with the reason: no email address, duplicate address, suppressed (the address is bouncing or complained), or unsubscribed. The send carries the preview's audience fingerprint. If the audience changed in between, the send is refused with 409 `audience_changed` and the admin is asked to review again.
- Several sessions in one send (#1030): an admin can tick several sessions. A family in two of them gets one copy. Single-session campaigns are stored exactly as before; a multi-session one is stored as a new `sessions` audience type.
- Invoice ops digest (#1033): the daily digest now counts the invoices emailed, the autopay notices sent and the sends that failed in the same run that minted them (new totals `mint_emailed`, `mint_email_failed`, `mint_skipped_autopay`, `mint_autopay_notified` folded into the existing keys, plus `invoice_mint_send_failed`). A tick whose only news is a failed send pass now produces a digest instead of staying silent.
- Waiver invoices (#1035): a fully waived month (gross tuition, net $0) is emailed by the monthly send pass with "No payment required", never "contact the academy to arrange payment", and never as an autopay "will be charged" notice. An owner can send a hand-billed draft whose charges are fully offset by a waiver; a blank draft is still refused. The invoice email lists every discount, waiver and credit line in its public wording. A coach-child line reads "Coach benefit: fees covered by <academy name>". A one-time adjustment's required reason and the acting owner are recorded in the billing audit trail.

## Deploy notes
Deploy backend and frontend together: the composer calls the new preview route and sends `session_ids` plus `expected_audience_fingerprint`. No migration. After deploy, the next daily send pass emails this period's not-yet-sent fully waived invoices once ("No payment required"). Earlier periods are not swept.

## Risk / rollback
The preview and the exclusion reasons reuse the sender's own suppression, preference and prospect gates read-only, so nothing a gate blocks can be sent. Waiver delivery adds one branch to the send query (`total_cents` 0 with a positive subtotal) and keeps zero balances out of checkout, autopay notices and late fees. Revert the PR to roll back; stored `sessions` campaigns stay as history and are not re-sent.
