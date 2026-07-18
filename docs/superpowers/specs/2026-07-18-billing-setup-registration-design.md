# Billing Setup — Payment Registration & Charge Design

**Date:** 2026-07-18
**Status:** Approved (design)
**Author:** RamC (with Claude)

## Problem

Admins need one place to see which of their families are set up to pay through
Stripe, nudge the ones who aren't to finish setup, and charge the ones who are.
Today the pieces exist but are scattered: parent Stripe customers live in
`parent_billing_customers`, login invites in identity, and charging in the
billing autopay use case. There is no single view that answers "who can I
charge, and who still needs to sign up?"

## Goal

A dedicated admin **"Billing Setup"** page that, per paying parent, shows
registration status, saved card, autopay state, and outstanding balance — and
offers the right next action (invite / add-card reminder / charge / enable
autopay) based on that parent's state.

## Non-goals (v1)

- Bulk actions (select many parents → send invites). Deferred; single-row
  actions only in v1.
- Franchise / cross-academy rollup.
- Parent-facing changes. This is an admin surface; it reuses the existing
  parent card-setup and password-set flows unchanged.

## Status model (parent-level)

Registration status is a property of the **parent (payer)**, not the student,
because the Stripe customer and saved card live on the parent. Siblings share
one status.

| State | Condition | Badge | Primary action |
|---|---|---|---|
| **No account** | no Firebase login account for the parent | grey — "Not invited" | Send login invite |
| **Account, no card** | has a login account, no saved payment method | amber — "No card" | Send add-card reminder |
| **Card on file** | `parent_billing_customers` has a primary payment method | green — "Registered" | Charge now / Enable autopay |

"Registered" (green) is defined strictly as **has a chargeable saved card**.

**Autopay is per-enrollment (per-child), not per-parent.** The parent's
`parent_billing_customers` doc holds only the Stripe customer + saved card;
each child's enrollment carries its own autopay on/off/paused state
(`student_billing_enrollments`, billing-owned — see
`EnrollmentAutopayStateRepository`). On this parent-grouped page autopay is
therefore shown as an **aggregate** ("autopay on for N of M children"), and the
**"Enable autopay" action turns it on for all of the parent's eligible
enrollments** (those with a card on file and a legal transition to `active`).

### Deriving "has a card"
A parent has a card when their `parent_billing_customers` row has a primary
payment method — i.e. `payment_method_label`/`payment_method_last4` (or the
`primary_*` variant) is present, or `autopay_payment_methods` contains a
primary entry. This is display-only data already projected by migration
`0144_parent_payment_method_display`; no raw PAN is read.

## Architecture

### Read model (billing context)
New read use case in `backend/v2/contexts/billing/application/use_cases/`
(e.g. `billing_setup_registration.py`) that, scoped to the resolved
`academy_id`, assembles one row per parent by joining:

- `parent_billing_customers` → `stripe_customer_id`, saved-card display fields
- **per-enrollment autopay state** (`EnrollmentAutopayStateRepository`,
  billing-owned) → count active vs eligible enrollments for the parent's children
- **identity** (via a port) → whether the parent has a login account
- **enrollment** (via a port) → the parent's students (ids + display names)
- **billing ledger** → outstanding balance per parent (sum of
  `balance_due_cents` across open invoices)

Cross-context signals (login-account existence, student roster) are obtained
through **Protocol ports defined in the billing application layer and wired in
composition** — billing does not import the identity or enrollment contexts
directly. This follows the repo's DDD boundary rules (see boundary-reviewer /
tenant-isolation conventions).

Output row (`BillingSetupRow`, frozen pydantic):
- `parent_id`, `parent_name`, `parent_email`
- `students: list[{student_id, full_name}]`
- `registration_state: "no_account" | "account_no_card" | "card_on_file"`
- `card_label: str | None` (e.g. "Visa"), `card_last4: str | None`
- `autopay_active_count: int`, `autopay_eligible_count: int` (per-child aggregate;
  eligible = enrollments that can legally go `active` and have a card on file)
- `outstanding_balance_cents: int`
- `last_invited_at: datetime | None`

The list endpoint is paginated (cursor, matching existing admin directory
conventions) and supports a `status` filter and a name search term.

### Endpoints (admin interface, tenant-scoped)
New route module `backend/v2/interfaces/admin/billing_setup_routes.py`,
registered in the admin router. All resolve `academy_id` via the existing
admin deps and authorize as admin.

- `GET /admin/billing/setup` — paginated list of `BillingSetupRow`, with
  `status` and `q` (name search) query params, plus a summary block
  (`families_total`, `families_registered`, `families_no_card`,
  `outstanding_total_cents`).
- `POST /admin/billing/setup/{parent_id}/invite` — **context-aware**:
  - no account → `SendLoginInvite` (set-password email)
  - account but no card → add-card reminder email (link to the existing
    autopay / SetupIntent card-setup checkout)
  Records/refreshes `last_invited_at`. Resend is allowed and does not create a
  duplicate account.
- `POST /admin/billing/setup/{parent_id}/charge` — charge the parent's
  outstanding balance now via `ChargeInvoiceViaAutopay`. Guard: 400 if no card
  on file or zero balance.
- `POST /admin/billing/setup/{parent_id}/autopay/enable` — enable autopay for
  ALL of the parent's eligible enrollments via the per-enrollment transition.
  Guard: 400 if no card on file; skips enrollments with no legal transition and
  returns how many were enabled.

### Action wiring (reuse existing use cases)
- **Login invite** → `contexts/identity/.../send_login_invite.SendLoginInvite`.
- **Add-card reminder** → thin new use case that composes the existing parent
  autopay/card-setup checkout link with the identity `InviteEmailPort`-style
  send. No new Stripe flow — it points the parent at the card-setup checkout
  that already exists (`CompleteAutopaySetup` consumes the result).
- **Charge now** → `contexts/billing/.../charge_invoice_via_autopay.ChargeInvoiceViaAutopay`.
- **Enable autopay** → per-enrollment autopay status transition
  (`offered`/`paused` → `active`) applied across the parent's eligible
  enrollments, reusing the autopay status state machine.

## Frontend

New admin page **"Billing Setup"** (route + nav entry alongside existing
billing admin pages).

- **Summary header:** "X of Y families registered · Z missing a card ·
  $N outstanding".
- **Grouped by parent (payer)**; students rendered as chips under the parent.
- **Columns:** parent (name/email + student chips), status badge, card
  (`Visa ···· 4242`), autopay badge ("N/M children"), outstanding balance, actions.
- **Filters:** All / Not invited / No card / Chargeable + name search.
- **Row actions adapt to state:**
  - Invite (label reflects sub-case: "Send invite" vs "Remind: add card")
  - Charge now — shown only when card on file AND balance > 0
  - Enable autopay — shown when card on file AND at least one eligible
    enrollment is not yet active (enables all of them)
- Shows "Invited {date}" with a **resend** affordance when `last_invited_at`
  is set.

## Error handling

- **Charge:** surface the Stripe decline reason from `ChargeResult` in a toast;
  leave the row chargeable so the admin can retry. Endpoint guards against
  no-card / zero-balance with a 400 (UI also hides the button).
- **Invite:** surface `InviteEmailOutcome.failed_reason` on send failure.
  Re-invite is safe and idempotent with respect to account creation.
- **Autopay enable:** 400 if no card; surface illegal-transition errors from
  the state machine as a clear message.

## Testing

- **Unit:** status derivation across all three states (no account / account no
  card / card on file), and the autopay active/eligible counts and
  outstanding-balance projections. Cover the "primary payment method present" boundary.
- **Interface:** each action endpoint — success path plus guardrails:
  - charge with no card → 400; charge with zero balance → 400
  - invite when already card-on-file → sensible no-op / not-applicable
  - autopay enable with no card → 400
- Reuse existing billing/identity test factories and the admin billing test
  harness (`tests/interface/test_admin_billing.py` patterns).

## Rollout

- Additive: new read model, new routes, new page. No schema migration required
  (all fields already exist via `0129`, `0142`, `0144`).
- Ship behind the standard admin nav; no feature flag needed unless one is
  preferred for staged release.
