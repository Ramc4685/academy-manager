# Parent self-service switches + payment instructions (server-side)

PR: #TBD

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
  `SelfCancelEnrollment`, `RequestEnrollmentPause`, and
  `ConfirmWaitlistOffer` (only when `parent_id` is set — a staff/admin
  confirm is never gated) now raise `ParentActionDisabled` (`code =
  "parent_action_disabled"`, HTTP 403, message "Your academy handles this
  directly. Please contact them.") when the matching switch is off.
- The admin `PUT/GET /admin/self-service/policy` route accepts and returns
  the new switches and `payment_instructions` alongside the existing six
  fields, still as a partial write (money audit X5's `$set`-only-what-changed
  contract is unchanged).
- The parent BFF's `GET /parent/academy` payload gains a `self_service`
  object carrying the five switches, so the parent shell can read them from
  the academy data it already loads on every screen (`ParentAcademyView` /
  `frontend/lib/api/parent.ts`'s `ParentAcademy.self_service`). The
  `stubParentAcademy` e2e fixture returns all-true switches.
- Free trial requests (the sixth action in the spec) reuse the existing
  Public page "Accept free trial requests" toggle
  (`identity.PublicPageSettings.trials_open`, edited in the Public page
  settings panel) rather than a new switch — see Open questions below for
  what wiring that reuse into the parent-authenticated trial-request route
  still needs.

## Deploy notes

- No migration (0208 or otherwise). Defaults are applied at read time by
  Pydantic field defaults on `ParentSelfServicePolicy` / the Mongo repo's
  `model_validate`.
- No env or secret change.
- BLNO is unaffected: every switch defaults on and `payment_instructions` is
  empty, so nothing changes for the only live academy until an admin
  explicitly turns a switch off or fills in payment instructions.

## Risk / rollback

- Low for the shipped slice: enforcement is additive (a new 403 branch at
  the top of each use case's `execute`), and the payload addition is
  additive (`self_service` is a new optional-shaped field parents' clients
  don't yet read).
- Not yet shipped in this PR (see follow-ups): the admin "What parents can
  do in the app" settings card, parent UI hiding of the six actions, the
  waitlist-off email/claim-link change, and payment-instructions rendering
  on the parent invoice screen/email. Enforcement without UI hiding means a
  parent can still see a now-403'd action until the frontend catches up —
  low risk (a clear contact-the-academy message, no data exposure) but not
  the full spec.
- Rollback: revert this PR's merge commit. The new fields are additive and
  ignorable by older code (Pydantic defaults cover their absence either
  way).
