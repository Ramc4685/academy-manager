# Parent self-service switches + payment instructions

PR: #1003

## What changed

- `ParentSelfServicePolicy` (the existing per-academy self-service policy
  record) gains five on/off switches — `can_report_absence`,
  `can_request_makeup`, `can_request_pause`, `can_request_cancel`,
  `can_claim_waitlist_offer` — and a `payment_instructions` field (owner
  plain text, max 1000 chars, empty by default). All switches default
  `True` (today's behaviour); a stored policy document written before this
  change has none of these keys and validates to the same defaults, so no
  migration or backfill is needed.
- Server-side enforcement: `SubmitAbsenceNotice`, `SubmitMakeupRequest`,
  `SelfCancelEnrollment`, `RequestEnrollmentPause`, `ConfirmWaitlistOffer`
  (only when `parent_id` is set — a staff/admin confirm is never gated), and
  now `SubmitTrialRequest`, all raise `ParentActionDisabled` (`code =
  "parent_action_disabled"`, HTTP 403, message "Your academy handles this
  directly. Please contact them.") when the matching switch is off.
- **Admin settings UI**: the Self-service settings panel gains a "What
  parents can do in the app" card with the five switches, plus a note
  linking to the Public page panel for the trials toggle
  (`frontend/components/admin/settings/self-service-panel.tsx`).
- **Parent UI hides (not disables) each action when off**: the Requests page
  hides the Absences/Makeups/Trials tab whose switch is off (and its own
  tab strip when only one remains); My Children hides "Report absence" and
  the Pause/Cancel buttons; the waitlist offer card hides Confirm/Decline
  and shows a contact-the-academy line instead. All read `self_service` off
  the existing `GET /parent/academy` payload (`ParentAcademy.self_service`
  in `frontend/lib/api/parent.ts`), extended with `can_request_trial`
  (reflects the Public page toggle). `stubParentAcademy` and the affected
  clean-console e2e stubs carry the new field.
- The admin `PUT/GET /admin/self-service/policy` route accepts and returns
  the new switches and `payment_instructions` alongside the existing six
  fields, still as a partial write (money audit X5's `$set`-only-what-changed
  contract is unchanged).
- Free trial requests reuse the existing Public page "Accept free trial
  requests" toggle (`identity.PublicPageSettings.trials_open`) rather than a
  new switch: `SubmitTrialRequest` now takes an optional `trials_open` gate
  (composed in `composition/parent.py` off the academy's `public_page` doc)
  and 403s the same way as the other five actions when it is off.
- **Waitlist-offer email**: when `can_claim_waitlist_offer` is off, the "a
  seat opened, claim it" email no longer carries the claim link (the
  read-only "offer expired / view your requests" email is unaffected — it
  was never a claim action). Wired through `RosterAlertAdapter` in
  `composition/roster_notifications.py`, read at send time so a switch
  flipped mid-window takes effect on the next send.
- **Payment instructions rendering**: shown, escaped and whitespace-preserved
  (`white-space: pre-wrap`), on the parent invoice/pay screen when an
  invoice is expanded (`frontend/app/(parent)/parent/payments/page.tsx`) and
  in the invoice email body (`InvoiceEmailAdapter.send_invoice_email` in
  `composition/email_adapters.py`, reading the self-service policy). Empty
  string renders nothing in either place — BLNO unchanged.
- Saved next to the offline payment methods setting: a "Payment
  instructions" field on the Billing rules → Offline payments card
  (`frontend/components/admin/settings/offline-payments-card.tsx`), backed
  by the same self-service policy record and its 1000-char server-side
  limit.

## Deploy notes

- No migration (0208 or otherwise). Defaults are applied at read time by
  Pydantic field defaults on `ParentSelfServicePolicy` / the Mongo repo's
  `model_validate`.
- No env or secret change.
- BLNO is unaffected: every switch defaults on, `payment_instructions` is
  empty (nothing renders anywhere), and the trials-open gate reads the
  existing Public page toggle, whose default is also on. Nothing changes for
  the only live academy until an admin explicitly turns a switch off or
  fills in payment instructions.

## Risk / rollback

- Low: enforcement is additive (a new 403 branch at the top of each use
  case's `execute`), the payload additions are additive fields older clients
  ignore, and the email/UI changes only remove or hide content when a
  switch is explicitly off (an admin action, not a default).
- Rollback: revert this PR's merge commit. The new fields are additive and
  ignorable by older code (Pydantic defaults cover their absence either
  way).

## Open questions

- The waitlist-off offer email still says "confirm by then to claim it" in
  its body copy even with the claim button/link removed, since the shared
  renderer (`render_waitlist_offer_email`) does not yet branch its copy on
  `can_claim`. The link itself is gone (the spec's hard requirement), but the
  copy could read better ("contact the academy to claim this seat") — filed
  as a follow-up rather than done here to keep the diff to the spec's literal
  ask.
- `InvoiceEmailAdapter`'s family-contact CC copy (L1b2, "you are receiving a
  copy...") does not carry the payment instructions block, only the
  parent's own copy does. The spec says "invoice email body", which this
  reads as the parent's own email; flagging in case the CC should match.
