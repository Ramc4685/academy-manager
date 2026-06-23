# stripe paid invoice shows unpaid

## Current State

Status: active

## Problem

Customer Stripe payment succeeded but app billing invoice still shows unpaid after issue #224 app-owned billing change

## Changed Files

- None recorded yet.

## Log

- 2026-06-22T11:41:37 main/NA: Task ledger created.
- 2026-06-22T11:41:45 main/working: Started read-only investigation. User reports Stripe succeeded but June app invoice shows unpaid after issue #224 app-owned billing change.
- 2026-06-22T11:45:41 main/working: Code inspection: admin Stripe sync dialog calls /admin/billing/reconcile and retrieves a Checkout Session, then updates legacy payments only. Issue #224 scheduled reconciliation repairs app-owned ledger invoices only from succeeded PaymentIntents carrying academy/invoice metadata. The reported first transaction appears to be the old subscription creation path, so it will not close the new app-owned June invoice automatically.
- 2026-06-22T14:07:38 main/working: Applied local academy_manager_saas_staging ledger repair for Jayaparthiban June invoice using backend ReconcileStripePaymentIntents path with PaymentIntent pi_3Tkr0CRMJDJBjoQz1aaNrLeP. Created deterministic ledger payment and allocation; no Stripe charge/refund was made.
- 2026-06-22T14:10:59 main/working: Investigating two more reported paid-but-pending students: Kabilan Chandran and Nigazhini Manoj. Starting read-only Mongo audit of invoices, ledger_payments, allocations, and reconciliation runs.
- 2026-06-22T14:13:07 main/working: Applied correction for Kabilan/Nigazhini and fixed prior PI attribution: moved pi_3Tkr0CRMJDJBjoQz1aaNrLeP to Nigazhini Manoj, added pi_3TkuLpRMJDJBjoQz14yIdrTu for Kabilan Chandran, and left Jayaparthiban paid under a separate subscription-creation reconciliation reference without claiming Nigazhini PI. No Stripe charge/refund made.
- 2026-06-22T14:38:03 main/working: Checking whether current open/pending app invoices will reconcile correctly when paid through the current invoice payment flow.
## Verification

- No verification recorded yet.
- 2026-06-22T11:44:40: Read-only Mongo audit of academy_manager_saas_staging: Jayaparthiban/Jawaharbabu June 2026 invoice inv-from-pay_blno_jawaharbabuj_jayaparthiban_jawaharbab_jun2026 is open with balance_due_cents=6000 and has no June ledger_payment/payment_allocation; April/May invoices are paid with ledger payments and allocations. Scheduled billing_reconciliation_runs for blno scanned=0 because there are no app-owned Stripe PaymentIntent IDs in the staging DB.
- 2026-06-22T11:45:41: Attempted Stripe connector read-only verification for customer/payment intents; connector returned INVALID_ARGUMENT Unknown tool for list_customers and list_payment_intents, so live Stripe object relationship could not be independently fetched from the connector.
- 2026-06-22T14:07:52: Post-repair Mongo verification: invoice inv-from-pay_blno_jawaharbabuj_jayaparthiban_jawaharbab_jun2026 status=paid, balance_due_cents=0; ledger payment ledger-pay-reconcile:pi_3Tkr0CRMJDJBjoQz1aaNrLeP amount_cents=6000 status=succeeded payment_method=stripe_autopay unapplied_amount_cents=0; allocation 01KVRBNSDHK5N6SCZ7R4PH1NAD links payment to invoice for 6000 cents.
- 2026-06-22T14:08:29: Final post-repair verification: invoice now status=paid, total_cents=6000, balance_due_cents=0, stripe_payment_intent_id=pi_3Tkr0CRMJDJBjoQz1aaNrLeP. Ledger payment paid_at adjusted to 2026-06-11T21:05:00Z from Stripe screenshot and notes state no new charge made.
- 2026-06-22T14:13:17: Post-correction verification: Nigazhini June invoice paid/balance 0 with PI pi_3Tkr0CRMJDJBjoQz1aaNrLeP; Kabilan June invoice paid/balance 0 with PI pi_3TkuLpRMJDJBjoQz14yIdrTu; Jayaparthiban June invoice remains paid/balance 0 using separate subscription-creation payment reference. Recent scheduled reconciliation runs had scanned=0, repaired=0, failed=0 because these payments are not visible to app-owned metadata search.
- 2026-06-22T14:39:01: Current pending invoice payment check: 48 open/partially paid invoices in academy_manager_saas_staging after confirmed repairs. Single-invoice Checkout path includes invoice_id/source/academy_id/parent_id on Checkout Session and webhook can allocate it. However create_invoice_checkout_session does not set payment_intent_data.metadata, while scheduled reconciliation searches PaymentIntent metadata; therefore missed webhooks for current invoice Checkout payments may still scan 0. Multi-invoice balance checkout uses invoice_ids metadata, while current webhook handler expects invoice_id only.
## Reusable Lessons

- None recorded yet.
