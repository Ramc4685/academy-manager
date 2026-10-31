# Offline payment methods setting drives the payment dialogs

PR: #993

## What changed

- Every incoming-payment dialog (Collections `RecordPaymentDialog`, `MarkPaidDialog`, `InvoiceDialog`'s manual-payment tab, and the student billing-dialogs `RecordPaymentDialog`) hardcoded the same six-option method list (`Cash, Check, Zelle, Venmo, Bank transfer, Other`). There was no way for an owner to say which of those an academy actually accepts.
- A new `academies.manual_methods` field, set only through a new owner-only setting, now controls which methods those dialogs offer. **Read-time default, not a migration**: a stored list only counts once an owner save sets `manual_methods_updated_at`. Until that marker exists, every academy reads all six methods in the same order the dialogs always showed — so nothing changes for any academy that has never touched this setting, including BLNO.
- New endpoints: `GET /api/v2/admin/academy/payment-methods` (owner, admin, or billing staff can read) and `PUT` on the same path (owner-only), capped at 20 items of at most 32 characters, requiring at least one method, 422 on an invalid method name. Every save writes a `payment_methods_changed` billing audit entry.
- New **Offline payments** card under Admin Settings -> Billing rules (owner-only) with checkboxes, a minimum-one-method guard, and its own Save. The existing read-only "Manual methods" chips on the Payments settings gateway panel now show all six for an academy that has not saved a choice yet (previously showed the unused `CASH/CHECK` default, which the dialogs never actually offered).
- `RecordManualPayment` still accepts all six methods regardless of the setting -- recording a payment is never blocked by this. Enforcing the chosen list on the write path is a later phase.
- Folded into the same PR: `MarkPaidDialog`, `InvoiceDialog`, and the buckets `RecordPaymentDialog` are mounted unconditionally by their parent tabs (only *visibility* toggles on a `payment`/`open` prop), so the new read needed an `enabled` gate to avoid firing on every tab load instead of only while a dialog is open. No production behavior change (it was already keyed off a prop that only became true while a dialog was open); this only avoids an unnecessary network call on every load of the payments and family billing tabs.

## Deploy notes

- No migration. `manual_methods_updated_at` is written only on an owner's first save of this setting; nothing needs a backfill, and on-boot migrations are off in prod regardless.
- Safe to deploy independently of any other in-flight PR.

## Risk / rollback

- Main risk: none identified for existing academies. Every academy without a saved choice -- which today is every academy, since this setting has never existed before -- reads all six methods, identical to what the dialogs already hardcoded. BLNO's dialogs, its Payments settings chips (now showing all six instead of the unused two-method default), and its bills/emails/times/links are unaffected.
- Rollback: revert this PR. No stored data needs to be undone -- an academy that saved a choice under the new setting simply reverts to the old code's hardcoded six-option dialogs, and the `manual_methods`/`manual_methods_updated_at` fields on `academies` are simply unread again.
