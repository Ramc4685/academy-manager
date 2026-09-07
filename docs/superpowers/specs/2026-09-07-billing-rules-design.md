# Settings → Billing rules — design

Date: 2026-09-07. Owner decisions from the brainstorming session are recorded inline.
Companion documents: the billing surface inventory and wireframes (artifact links in the
PR description), and specs 1–4. This is the fifth and last spec of the admin billing
redesign; it covers the Settings billing panels and the routes behind them.

## 1. Purpose

Every number that decides when money moves should be visible on one page, and it should
be honest about which of those numbers the software actually obeys.

Today they are scattered and partly fictional. The Fees panel offers a late fee and grace
days that **no code ever reads** — nothing in the product charges a late fee — and carries
a `default_monthly_cents` field that is in the form state but has no input, so it can
never be saved. The invoice-schedule panel sits beside it with the two settings that are
real. The rules that matter most — cancel mid-month owes the full month, join mid-month is
prorated, paused months are not invoiced — are hard-coded policy from PR #654 and appear
nowhere in the UI, so the owner has no way to check what the system will do.

Billing rules replaces both panels with one, groups the numbers by the decision they
serve, and marks each one editable or fixed. A fixed rule is shown, not hidden: "cancel
mid-month = full month owed" is a real answer to a real question even though there is no
switch beside it.

Out of scope: implementing late-fee assessment, implementing scheduled reminders, and
changing any policy. Nothing about how money moves changes in this spec; no migration.

## 2. Owner decisions

| Question | Decision |
|---|---|
| Late fee and grace days, which nothing reads | **Keep them editable and persisted**, with a plain line on the panel saying no late fee is charged automatically yet. The values are ready for when the feature lands. |
| Reminders to manual payers | **Read-only.** There is no scheduled reminder job; the panel says reminders are sent by hand from the Payments page. No switch that does nothing. |
| `default_monthly_cents` | Removed. |

## 3. The panel

One panel at `?panel=billing-rules`, owner-only, replacing `FeesPanel` and
`InvoiceSchedulePanel`. Four boxes, per wireframe 5. Every row is either **editable**
(an input that saves) or **fixed** (a stated value with a one-line explanation of where
the behaviour comes from).

### Monthly invoicing

| Row | Kind | Source |
|---|---|---|
| Invoice day of month | editable, 1–28 | `billing_settings.billing_day` |
| Days until due | editable, 0–60 | `billing_settings.invoice_due_days` |
| Autopay charge time | fixed: "09:00 academy time on the due date" | `first_attempt_local_hour` in the dunning repository |
| Retry schedule after a failed charge | fixed: "same day, then 3, 5 and 7 days later, then autopay switches off" | `DUNNING_SCHEDULE_DAYS` and `MAX_DUNNING_ATTEMPTS` |

The two editable rows keep their current validation, endpoint and audit entry.

### Late payments

| Row | Kind | Source |
|---|---|---|
| Grace days after due | editable | `academies.fees.grace_days` |
| Late fee | editable, dollars | `academies.fees.late_fee_cents` |

Both carry one shared note: **"Not applied automatically yet — these values are stored for
when late fees ship."** This is the honest description of today's behaviour, and it is
the whole reason the box does not silently lie.

### Leaving and pausing

All fixed, all stating the #654 and #651 decisions:

| Row | Value | Why |
|---|---|---|
| Cancel mid-month | Full month owed, no refund | `SelfCancelEnrollment` keeps the cancellation month payable and voids later invoices |
| Join mid-month | Prorated from the start date | `domain/proration.py`, policy `first-month-proration-v1` |
| Paused months | Not invoiced | the generator skips `paused` enrollments |
| Cancellation notice | **editable**, days | `ParentSelfServicePolicy.cancellation_minimum_notice_days` |
| Late-cancellation fee | **editable**, dollars | `ParentSelfServicePolicy.cancellation_fee_cents` |

The last two are already editable on the Self-service panel and genuinely enforced by
`compute_self_cancel_terms`. They appear here because this is where an owner looks for
them; the Self-service panel keeps its own copy of the wider parent-self-service policy
and both write through the same endpoint, so there is one stored value, not two.

### Parent messages

| Row | Kind | Value |
|---|---|---|
| Autopay notice on invoice day | fixed | On — autopay parents get a notice instead of the invoice email |
| Receipt after a successful charge | fixed | On |
| Payment failure notice | fixed | Sent by the dunning ladder |
| Reminders to manual payers | fixed | "Sent by hand from Payments. No automatic schedule." |

None of these has a per-academy setting today and this spec does not invent one. Each row
says what happens, so the panel answers "will the parent hear from us?" without offering a
control that does nothing.

## 4. Backend

### 4.1 One read, one write

Two panels today mean two reads and two writes across two contexts — `academies.fees` in
identity and `billing_settings` in billing. The panel gets one pair, and the existing
routes stay for their other callers:

- `GET /admin/billing/rules` — admin persona, read-only, returns every row above,
  editable and fixed alike, each with its value and an `editable` flag. The fixed values
  are read from the constants that govern the behaviour, never re-typed as literals in the
  view: the charge hour from the dunning repository, the ladder from the dunning domain,
  the proration policy version from `domain/proration.py`. If a constant changes, the page
  changes with it.
- `PUT /admin/billing/rules` — **owner only**, body carries only the editable fields, all
  optional; applies each to its existing store through its existing use case
  (`SetInvoiceScheduleSettings`, the academy fees update, the self-service policy update),
  and writes **one** `billing_audit_log` entry with a new `billing_rules_changed` action
  carrying `before` and `after` for exactly the fields that changed, the actor and an
  optional reason. A request that changes nothing is a no-op and writes no audit entry,
  matching `SetInvoiceScheduleSettings` today.

This closes a real gap: fee changes are currently **unaudited**, because
`UpdateAcademyFeesUseCase` writes no audit entry at all.

Wiring goes in a new `composition/billing_rules.py` on `app.state.admin_billing_rules`,
with routes in a new `interfaces/admin/billing_rules_routes.py`. `composition/admin.py`
is not touched.

### 4.2 Validation

The write validates before it touches any store, so a bad late fee cannot leave a saved
billing day behind it: `billing_day` 1–28, `invoice_due_days` 0–60, `grace_days` 0–60,
`late_fee_cents` 0–100000, `cancellation_minimum_notice_days` 0–90,
`cancellation_fee_cents` 0–100000. 422 with the offending field on failure. The academy
fees view has **no bounds today** — a negative late fee is currently accepted — so this
spec adds them at the new route and leaves the old route's behaviour alone.

Writes are applied in a fixed order and each is idempotent; if a later write fails, the
response is 500 and the audit entry records only the fields that actually changed, so the
log never claims a change that did not happen.

### 4.3 `default_monthly_cents` removed

Removed from `AdminFeesView`, `UpdateAdminFeesRequest`, `GetAcademyFeesUseCase`,
`UpdateAcademyFeesUseCase`, the academy bootstrap document, both seed scripts, the
frontend type and the fees form state, plus the tests and e2e stubs that name it. The
legacy alias `default_session_price_cents` goes with it.

Nothing prices anything from this field; it has no reader outside the fees read and write
path. Existing Mongo documents keep the orphan key, which is harmless — the `academies`
collection has no validator forbidding it — and no migration is needed.

## 5. Page

`?panel=billing-rules` replaces `?panel=fees` in the tab list; a deep link to
`?panel=fees` renders Billing rules so a bookmark still lands somewhere sensible. The tab
stays in `OWNER_ONLY_SETTINGS_PANELS`.

- One save button for the whole panel, disabled until something changes, showing which
  fields will be written.
- Fixed rows render as a label and a value in muted type, with the explanation beneath.
  They are visibly not inputs — no box, no cursor.
- The late-payments box carries its "not applied automatically yet" note above the two
  inputs, not below, so it is read before the fields are filled in.
- Save errors render inline against the offending field; a partial failure reports which
  fields were saved.
- `FeesPanel` and `InvoiceSchedulePanel` are deleted; the self-service panel keeps its
  cancellation fields and both write through the same policy endpoint.

## 6. Testing

Backend:

- Unit tests for the rules assembler: every fixed value derived from its governing
  constant (a test that changes `DUNNING_SCHEDULE_DAYS` and sees the view change, which is
  what stops the page drifting from the worker), and the editable set matching the write
  model.
- Unit tests for the write: only changed fields audited, a no-op writing nothing, each
  bound rejected, an invalid field rejected before any store is touched, and one audit
  entry per request with `billing_rules_changed`.
- Interface tests: `GET` 200 for admin, `PUT` 200 for owner and **404 for admin**, 422 per
  bound, the structural owner-gate test updated, and the existing fees and
  invoice-schedule routes still passing unchanged.
- The `default_monthly_cents` removal: `test_admin_settings.py` and
  `test_academy_use_cases.py` updated to the two-field fees contract.

Frontend:

- Node test for the panel view model: editable versus fixed rows, dollars-to-cents
  round-tripping, the changed-field diff the save button reports.
- Playwright `admin-billing-rules.spec.ts`: the four boxes render, fixed rows have no
  inputs, the late-fee note is present, saving posts only the changed fields, a bound
  violation renders inline, `?panel=fees` lands on Billing rules, and an admin (non-owner)
  gets the owner-only panel.
- `admin-session-creation-ui.spec.ts` fee and invoice-schedule tests rewritten to the new
  panel; `admin-shell.spec.ts` tab matrix updated; the `default_monthly_cents` stubs
  removed from four e2e specs.
- Inventory manifest: the `/admin/settings` entry's controls updated for the merged panel.
  Route count is unchanged.

## 7. Rollout

One PR. Backend first (read and write routes, audit action, validation), then the panel,
then the `default_monthly_cents` removal and its test and stub updates. No migration, no
data change, no env. Rollback is a revert; nothing this PR writes changes shape.

Release note: the merged panel, the new audited billing-rules write, the removed dead
field, and the explicit statement that late fees are stored but not charged.

## 8. Follow-ups this spec deliberately leaves

- Assess late fees automatically after the grace period, at which point the note on the
  late-payments box comes off. This is the one place in the redesign where the UI is
  currently ahead of the behaviour.
- A scheduled reminder job for manual payers, at which point the parent-messages box
  gains its first real control.
- Per-academy switches for the autopay notice and receipt, if an academy ever wants them
  off.
- Move `academies.fees` into `billing_settings` so billing rules live in one store; the
  new write endpoint already hides the split from the page, which is what makes that move
  safe to do later.
- The monthly generation job runs on the global scheduler timezone while the autopay
  charge is academy-local; unifying them is a behaviour change and belongs in its own PR.
