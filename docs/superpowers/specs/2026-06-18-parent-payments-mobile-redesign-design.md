# Parent Payments — mobile-first redesign

**Date:** 2026-06-18
**Status:** Approved (design), pending spec review
**Scope:** `frontend/app/(parent)/parent/payments/page.tsx` as the pilot; patterns to be reused across other parent pages in follow-ups.

## Problem

The parent Payments page is the most-used and most-broken parent screen on mobile:

1. **Invoice table overflows.** The invoice list is a `min-w-[640px]` table inside a `max-w-md` column. On a phone it scrolls horizontally and clips content — column headers render as "tatus" and buttons as "Retry paymer" (confirmed in a real screenshot).
2. **Off-theme.** The page uses generic neutral/blue Tailwind, while the parent shell (`(parent)/layout.tsx`) uses the "rally" design system (navy/cobalt header, gold accents, paper background). The page looks like a different app from the shell wrapping it.
3. **No clear primary actions.** Pay and autopay are buried among five stacked sections (credits, invoices, autopay, pause form, pause requests, history) with no hierarchy.

Parents land on `/parent/dashboard` at login; they reach this page by tapping **Payments**. When they do, the two jobs they care about are **pay what's owed** and **set up autopay** — both should be first-class.

## Goals

- Eliminate horizontal overflow; everything fits a phone column.
- Bring the page onto the rally design system so it matches the shell.
- Make **one-time payment** and **subscribe to autopay** the two primary actions (equal weight).
- Establish reusable mobile patterns (summary hero, status pills, action cards, collapsible secondary sections) for later parent-page work.

## Non-goals

- No redesign of other parent pages in this round (dashboard, children, progress, attendance, waivers) — they follow later using the patterns proven here.
- No changes to Stripe billing logic beyond the single new "pay full balance" endpoint described below.
- No change to the pause-request workflow's behavior (only its visual treatment).

## Design

### Information hierarchy (top to bottom)

1. **Header** — page title "Payments" + a compact "Billing portal" link (icon + label), not a heavy button.
2. **Balance hero** — dark card showing `Balance due $120.00`, a status chip (`N open invoices · autopay off/on`), and a full-width gold **Pay balance · $X** button (one-time checkout for all open invoices).
3. **Invoices** — card list (replaces the table). Each open invoice card shows period, status pill, amount due, a **Pay $X** button, and **View** (line items). Paid/void invoices collapse to a quiet single row.
4. **Autopay** — one card per enrollment: child name, schedule/level, inline autopay status, a **Subscribe to autopay** primary button, and a **Pause** secondary button. Retains existing status-aware labels ("Autopay on", "Retry autopay", "Payment setup pending", etc.).
5. **Available credit** — keep the existing emerald credit card when `creditBalance > 0`, restyled to the rally palette, placed directly under the hero.
6. **Secondary, collapsed** — Payment history and Pause requests collapse behind expandable rows so the page opens focused on pay + autopay.

### Pay actions (decision: both)

- **Hero "Pay balance"** — single Stripe checkout covering all open invoices. **Requires a new backend endpoint** (see below).
- **Per-invoice "Pay $X"** — reuses the existing `startParentInvoicePayment(invoiceId, …)` flow, restyled.

### Autopay actions

- **Subscribe to autopay** — reuses existing `startAutopay({ enrollment_id, success_url, cancel_url })`.
- Button label/disabled state driven by existing `autopayStatusText` / `autopayHelperText` / `subscription_status` logic — preserved as-is, only restyled.

### Backend addition: pay full balance

Today only per-invoice payment exists (`startParentInvoicePayment`). The hero needs a new parent billing endpoint that creates one Stripe Checkout session billing all of the parent's open (and partially_paid) invoices:

- New endpoint under the parent billing interface (mirror `start_parent_invoice_payment`'s auth, tenant scoping, and idempotency).
- Sums `balance_due_cents` across non-void open/partially_paid invoices; creates one checkout; returns `{ redirect_url }`.
- Frontend client fn `startParentBalancePayment({ success_url, cancel_url })` in `frontend/lib/api/parent.ts`.
- **Fallback if descoped:** drop the hero button and keep only per-invoice pay (zero backend change). User has chosen to keep the hero.

### Theming / components

- Use the rally tokens already used in `layout.tsx`: navy gradient surfaces, gold (`#facc15`/`#f59e0b`) primary, `var(--rally-paper)` background, `var(--rally-cobalt)`.
- Replace the table with an `InvoiceCard` list; extract small presentational pieces (`BalanceHero`, `InvoiceCard`, `AutopayCard`, `StatusPill`, `CollapsibleSection`) within the page file (or a local `_components` folder if the file grows past a clarity threshold).
- Keep `min-h-touch` on all tap targets (already a convention).
- Status pills: reuse/extend the existing `StatusBadge` palette, recolored to rally.

## Data flow

Unchanged query layer. The page keeps its existing React Query hooks (`listParentInvoices`, `listParentEnrollments`, `listParentPayments`, `listParentCredits`, `listParentPauseRequests`, `getParentInvoice`) and mutations (`startAutopay`, `startParentInvoicePayment`, `openBillingPortal`, `createParentPauseRequest`). One new mutation wraps `startParentBalancePayment`. Checkout-return invalidation (`?autopay=success`, `?invoice=paid`) is preserved; add `?balance=paid` handling mirroring `?invoice=paid`.

## Error handling

Preserve all existing error states and their `data-testid`s (`billing-portal-error`, `invoice-payment-error`, `autopay-error`, `payment-update-pending`, `autopay-checkout-confirming`). Add an equivalent balance-payment error state. Restyle to rally; do not remove.

## Testing

- Existing parent payments tests / `data-testid`s must keep passing — preserve `parent-payments`, `payments-list`, `payment-<id>`, and the error/status testids above.
- Add coverage for the new "pay balance" endpoint (request shape + sums only open/partially_paid, non-void invoices) following `test_stripe_gateway_request_shape.py` conventions.
- Verify no horizontal overflow at 360px width (manual + any existing viewport test).

## Reusable patterns (for later parent pages)

`BalanceHero`, `InvoiceCard`/action-card shape, `StatusPill`, and `CollapsibleSection` are written to be lifted into a shared parent component kit when dashboard/children/progress get the same treatment.
