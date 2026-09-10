# Departure actions from the student page — design

Date: 2026-09-10. Owner decisions from the brainstorming session are recorded inline.
First of four specs from the 2026-09-10 admin-UX session (the others: families
directory consolidation, birthdays and profile nudges, student page single view).

## 1. Purpose

A parent messages the admin: "we don't want to continue." The admin opens that child's
page — not the class roster — and needs to put the enrollment on hold or drop it right
there. Today the student page's Sessions tab offers only **Transfer**; Hold, Return, Drop
and Delete are reachable only from the class roster, and even there "Pause" still calls
the old seat-releasing endpoint.

What already exists and is reused, not rebuilt:

- The shared `DepartureActions` row component and its vocabulary (Transfer, Hold, Return,
  Drop, Delete) — PR #700.
- The seat-keeping hold on the backend: `POST /admin/enrollments/{id}/hold` (requires
  `return_on`, capped by `hold_max_days`), `POST …/return`, reclaim, monthly reminder,
  `EnrollmentDeparturePolicy` in settings — PRs #701, #705.
- The one withdraw path with a billing outcome (`WithdrawEnrollmentCommand`, #670) and
  the owner-gated delete.
- Frontend API clients `holdEnrollment` / `returnFromHold` in
  `frontend/lib/api/v2/departure-policy.ts` — written by #701, called by nothing.

The gap is purely the last mile: no Hold/Return dialog exists, the roster still wires
Pause/Resume, and the student page wires Transfer only. PR #700's description said the
departure "can be handled from the person rather than the class"; its diff did not do that.

## 2. Owner decisions

| Question | Decision |
|---|---|
| Scope of a "stop" | One family's enrollment in one class. Whole-class cancel is out of scope (it has its own `DELETE /sessions/{id}` with no UI — separate issue). |
| Pause vs cancel | Two distinct actions: **Hold** (seat kept, billing paused, return date required) and **Drop** (withdrawn, seat released, billing outcome per policy). |
| #697 | Already merged (backend). This spec finishes its frontend: Hold/Return replace Pause/Resume everywhere the row renders. |
| Parent notification | A toggle in the Hold and Drop dialogs. Default ON for Drop, OFF for Hold. The dialog always names who will be emailed. |
| Where | Student page Sessions tab (this spec) and the class roster (same component, so it comes for free). The family page gets the row later, once it has enrollment rows (spec 2 §6). |

## 3. Actions per row

`resolveDepartureActions` already decides layout; what changes is which actions each
surface passes in. One shared helper replaces `RosterPanel.rosterActionsFor`:

```
departureActionsFor(status) ->
  active  : [transfer, hold, drop, delete]
  held    : [return, transfer, drop, delete]
  paused  : [return, transfer, drop, delete]   # legacy rows until #703's vocab settles; Return calls /return
  other   : [delete]
```

Layout on the student page: **Transfer** stays the one inline button (existing pattern).
Hold/Return and Drop go into the row's overflow menu; Delete sits last in that menu behind
a separator, owner-gated (already implemented in the component). Fee and Discount links
stay where they are. Nothing new is inline, so the row does not wrap on tablet widths.

`pause` and `resume` are removed from `DepartureAction`; the roster's
`PauseEnrollmentDialog` is deleted. The `/pause` and `/resume` routes stay on the backend
for the parent pause-request approval flow (#616) — that flow is not touched here.

## 4. Dialogs

Dialogs move out of `app/(admin)/admin/sessions/[id]/dialogs.tsx` into
`components/admin/enrollment/` so both surfaces mount the same ones. `TransferEnrollment`,
`WithdrawalCredit` and `RemoveEnrollment` already exist and move unchanged except for the
new toggle.

### 4.1 Hold

Fields: return date (required; default today + 30; max today + `hold_max_days` from the
departure policy, with the cap shown in the helper text), reason (optional), **Email the
family** toggle (default off).

Consequence text, always shown: "Seat is kept. Billing pauses from the next invoice and
resumes on the return date. If the class fills, the longest-held family is asked to
return or drop first."

Calls `holdEnrollment(id, { return_on, reason, notify_family })`.

### 4.2 Return

Fields: reason (optional). Consequence: "Billing resumes with the next invoice." Calls
`returnFromHold(id, { reason, notify_family })`, toggle default off.

### 4.3 Drop

The existing `WithdrawalCreditDialog` (effective date, outcome per policy default, reason
required) gains the **Email the family** toggle, default on. Consequence text already
states seat, autopay, invoices and balance.

Calls `withdrawEnrollment(id, { …, notify_family })`.

## 5. Backend: the notify flag

`HoldEnrollmentRequest`, `ReturnFromHoldRequest` and the withdraw request each gain
`notify_family: bool = False` (drop's dialog sends `true` by default; the API default is
`false` so existing callers and tests are unchanged).

Sending follows the absence-notice pattern from #709: a best-effort notifier port on the
use case, adapter in `composition/`, claimed once per `(enrollment_id, event, seq)` via
`digest_claim`, TRANSACTIONAL category, never able to fail the write. The hold notifier
port (`HoldNotifier`) already exists for reclaim and reminders; it gains `hold_started`
and `hold_returned`. Withdraw gains a sibling `WithdrawalNotifier` with `dropped`.

Copy states the effective date and, for hold, the return date; for drop, the billing
outcome in plain words (credit / no credit / refund) using the policy vocabulary already
rendered in the dialog.

## 6. Past enrollments

No change: `PastEnrollmentsPanel` (#674) already renders who/when/why from the lifecycle
event. The reason typed in the dialog is what shows there, so the Drop reason stays
required and Hold's reason, when given, lands on the hold event.

## 7. Out of scope

- Whole-session cancel/pause UI.
- The family page action row (spec 2 defers it until that page has enrollment rows).
- Parent-initiated pause requests (#616) and their approval flow.
- Any change to hold reclaim, reminder cadence or billing deferral math.

## 8. Testing

- Unit: `departureActionsFor` table above; `resolveDepartureActions` overflow placement
  for the new sets.
- Backend: request DTO accepts and defaults `notify_family`; notifier is called once with
  the flag on, never with it off; a notifier failure does not fail the write (existing
  pattern tests to copy).
- e2e: `admin-enrollment-withdraw.spec.ts` gains Hold → Return from the student page and
  Drop from the student page with the past-enrollments row asserted. Roster spec updates
  Pause → Hold labels.
