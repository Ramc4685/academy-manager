# Parent money: one number, one date, per child (S57) and a printable receipt (S58)

Decision applied: **D-06 option 1**. "Due" means invoices already issued and unpaid. No estimate of next month. A receipt is a printable page for a paid invoice, not a PDF file and not an email.

## 1. Goal and the quotes it answers

A parent opens Payments from a reminder and must be able to say, in five seconds, "I owe $X by this date, for these children", or "I owe nothing".

- parent-busy: "I could not find what I owe next month, a receipt, or any sign that my sibling discount applies."
- parent-busy: "Payment history says 'succeeded' with no child's name."
- parent-busy: "A single 'what I owe' number with a pay or 'paid in cash' status."
- parent-new: "Prices in simple sentences and a total for two children."
- parent-busy: "'Manage class' on Payments goes to the Children page, not a class."

## 2. Entry points and navigation

- Bottom tab **Payments** (`/parent/payments`), the Home "amount due" banner, and invoice emails.
- Receipt: `/parent/payments/receipt/[invoiceId]` (new route), opened from **Receipt** on a paid invoice row. Back link returns to `/parent/payments`.
- Delete the top link "Looking for the next class date and time?" (parents land on Home since S20).

## 3. Layout

### 3.1 Payments, phone (375px), something is due

```
┌───────────────────────────────────────┐
│ Payments                 Billing portal│  h1 + existing ghost button
├───────────────────────────────────────┤
│ ┌───────────────────────────────────┐ │  Card, 3px top accent:
│ │ YOU OWE                           │ │  red if overdue, cobalt if not
│ │ $150.00                           │ │  Overline + BigNum 36px
│ │ Due Tue, Dec 1                    │ │  body 14px ink, one line
│ │ ───────────────────────────────── │ │
│ │ Sam Demo                          │ │  child line
│ │ Junior Beginners · November  $90.00│ │
│ │ Alex Demo                         │ │
│ │ Junior Beginners · November  $90.00│ │
│ │ Sibling discount            −$30.00│ │  discount line, green text
│ │ ───────────────────────────────── │ │
│ │ Total for your family      $150.00│ │  semibold, tabular
│ │ [        Pay $150.00            ] │ │  Button primary lg, full width
│ │ Secure checkout via Stripe        │ │  (or payment instructions, 3.4)
│ └───────────────────────────────────┘ │
│ $20.00 credit on your account. It     │  existing green credit card,
│ comes off your next invoice.          │  copy changed
│                                       │
│ INVOICES                              │  Overline
│ November 2026 · $150.00 due           │  period header (new)
│ ┌───────────────────────────────────┐ │
│ │ Sam Demo · Junior Beginners       │ │  child + class (new)
│ │ ● DUE   Due Dec 1          $60.00 │ │  Chip + amount
│ │ [ Pay $60.00 ]  [ View ]          │ │  existing buttons
│ └───────────────────────────────────┘ │
│ October 2026 · $150.00 paid           │
│ ┌───────────────────────────────────┐ │
│ │ Sam Demo · Junior Beginners       │ │
│ │ ● PAID  Paid in cash · Oct 3      │ │
│ │                           $60.00  │ │
│ │ View detail            Receipt →  │ │  two 44px text buttons
│ └───────────────────────────────────┘ │
│ ▸ Classes and autopay                 │  existing collapsible sections,
│ ▸ Pause requests                      │  unchanged order
│ ▸ Payment history                     │
└───────────────────────────────────────┘
```

### 3.2 Payments, phone, nothing due

```
│ ┌───────────────────────────────────┐ │  green top accent
│ │ YOU OWE                           │ │
│ │ $0.00                             │ │
│ │ Nothing to pay right now.         │ │
│ │ Last payment: $150.00 on Oct 3,   │ │  only when one exists
│ │ paid in cash.                     │ │
│ └───────────────────────────────────┘ │
```

### 3.3 Desktop (≥1024px)

Same single column, `max-w-2xl`, centred as the page is today. The summary card places the figure and date on the left and the Pay button on the right in one row; child lines sit below at full width. No table.

### 3.4 When the academy takes manual payments only

If `can_pay_online` is false, the Pay button is replaced by the academy's `payment_instructions` text in a bordered box titled "How to pay", plus "Tell the front desk when you have paid so they can mark it." Never a disabled Pay button.

### 3.5 Payment history row (inside the existing collapsible)

```
│ $60.00                        ● PAID  │
│ Sam Demo · November 2026              │  child names · what it paid for
│ Paid in cash · Oct 3, 2026            │  method_label · date
│ Refunded $20.00                       │  only if refunded
```

Remove the raw Stripe id line (`Invoice in_…` / `PaymentIntent pi_…`) from the parent view.

### 3.6 Receipt page (screen and print)

```
┌───────────────────────────────────────┐
│ ← Back to payments        [ Print ]   │  both print:hidden
│ ┌───────────────────────────────────┐ │  .receipt-print, white card
│ │ [logo] Demo Academy               │ │
│ │ 12 Court Lane, Normal IL          │ │  address, phone, email if set
│ │ (309) 555-0142 · hello@demo.test  │ │
│ │                                   │ │
│ │ RECEIPT                DEMO-202610-0003 │
│ │ Paid in full on Oct 3, 2026       │ │
│ │                                   │ │
│ │ Paid by     Demo Parent           │ │
│ │ For         Sam Demo              │ │
│ │ Period      October 2026          │ │
│ │ ───────────────────────────────── │ │
│ │ Junior Beginners tuition   $90.00 │ │  invoice lines as stored
│ │ Sibling discount          −$30.00 │ │
│ │ ───────────────────────────────── │ │
│ │ Total                      $60.00 │ │
│ │ ───────────────────────────────── │ │
│ │ Payments                          │ │
│ │ Oct 3, 2026 · Cash         $60.00 │ │  one row per allocation
│ │ Balance                     $0.00 │ │
│ │                                   │ │
│ │ This receipt was produced by      │ │  11px slate
│ │ Demo Academy using CourtMastr.    │ │
│ └───────────────────────────────────┘ │
└───────────────────────────────────────┘
```

Print: copy the `.waiver-print` `@media print` block in `frontend/components/waivers/signed-waiver-document.tsx` (hide everything, show only `.receipt-print`, no border, A4/Letter portrait, one page). Black text on white; the logo prints if present.

## 4. States

| State | Payments | Receipt |
|---|---|---|
| Loading | Summary card as `Skeleton variant="block" height="11rem"`, three line skeletons below. Replace the bare "Loading..." text. | `Skeleton variant="block" height="24rem"` |
| Empty (no invoices ever) | Summary card: "YOU OWE $0.00" + "No invoices yet. Your first invoice appears here when the academy sends it." (S24 copy stays below.) | n/a |
| Error | `ErrorNotice` "We could not load your payments. Check your connection and try again." with Retry. Nothing else renders; never show a partial money figure. | Red alert box: "We could not open this receipt. It may not be yours, or it is not paid yet." + Back link |
| Partial (summary loads, invoice list fails) | Summary card renders; list area shows inline "Could not load your invoices. Retry". Pay button in the summary still works (it calls the existing balance-payment endpoint). | n/a |
| Overdue | Date line: "Was due Sun, Nov 1 · 25 days ago" in status-red-800; top accent red; chip `overdue`. | n/a |
| Payment in flight | Existing banners stay ("Payment received — updating your balance…"). Summary Pay button disabled with "Processing…". | n/a |
| Success | After checkout return and refetch: summary shows the new figure; toast "Payment received. Thank you." via the existing return handling. | Print dialog opens from **Print** |

## 5. Exact copy

- Overline: `YOU OWE`. Never "Balance due" (replace the night "Balance hero" block; delete it).
- Date line: `Due {Tue, Dec 1}` / `Due today` / `Was due {Sun, Nov 1} · {n} days ago`.
- Two different due dates among unpaid invoices: `First payment due {date}` and each invoice row keeps its own date.
- Family total label: `Total for your family` (shown when 2+ child lines or any discount line; hidden for one child with no discount, where the big figure is enough).
- Already-paid line (partial payments): `Already paid` `−$X`.
- Nothing due: `Nothing to pay right now.`
- Credit card: `${X} credit on your account. It comes off your next invoice.`
- Payment status words (replace raw statuses everywhere on this page): succeeded `Paid`, pending `Processing`, failed `Did not go through`, refunded `Refunded`, partially_refunded `Partly refunded`, voided `Cancelled`.
- Method words (`method_label`, written by the backend): `Paid in cash`, `Paid by check`, `Paid by Zelle`, `Paid by Venmo`, `Paid by bank transfer`, `Paid by card`, `Paid by autopay`, fallback `Paid`.
- "Manage class" link becomes `Change or pause in Children` (it goes to `/parent/children`).
- Receipt button: `Receipt`. Print button: `Print or save as PDF`.
- Words: "class", never "session" (GLOSSARY.md).

## 6. Components

Reuse: `Card` (accent), `BigNum`, `Overline`, `Chip` (`paid`, `overdue`, `pending`; label override "DUE" on the `pending` family), `Button`, `Skeleton`, `ErrorNotice`, `EmptyState` from `frontend/components/ds/`; `formatAcademyDate` from `frontend/lib/format/academy-time.ts` (S05 rule); `money()` already in the page.

New, both small:
- `frontend/components/parent/money-summary-card.tsx`: renders the S57 block from the summary response. No arithmetic.
- `frontend/components/parent/receipt-document.tsx`: the printable receipt, modelled on `signed-waiver-document.tsx`.

Delete from `payments/page.tsx`: the `currentBalance` reduce (client-summed money), the night balance hero, `StatusPill`'s raw-status rendering for payments.

## 7. Data

### 7.1 New: `GET /api/v2/parent/money-summary`

Auth `require_persona("parent")`; family = `claims.user_id` and its aliases, via the same `ListParentInvoices` the invoice list uses (issue #932). Tenant = request academy. Wiring in `backend/v2/composition/parent_money_summary.py`; route and views in `backend/v2/interfaces/parent/money_views.py` (not `composition/parent.py`, not `views.py`).

```json
{
  "currency": "usd",
  "amount_due_cents": 15000,
  "due_date": "2026-12-01",
  "overdue": false,
  "days_overdue": 0,
  "multiple_due_dates": false,
  "can_pay_online": true,
  "lines": [
    {"kind": "child", "student_id": "…", "label": "Sam Demo", "detail": "Junior Beginners · November", "amount_cents": 9000},
    {"kind": "child", "student_id": "…", "label": "Alex Demo", "detail": "Junior Beginners · November", "amount_cents": 9000},
    {"kind": "discount", "label": "Sibling discount", "amount_cents": -3000},
    {"kind": "paid", "label": "Already paid", "amount_cents": 0}
  ],
  "periods": [
    {"period": "2026-11", "label": "November 2026", "billed_cents": 15000, "paid_cents": 0, "due_cents": 15000},
    {"period": "2026-10", "label": "October 2026", "billed_cents": 15000, "paid_cents": 15000, "due_cents": 0}
  ],
  "last_payment": {"amount_cents": 15000, "paid_on": "2026-10-03", "method_label": "Paid in cash"}
}
```

Rules, all in the backend:
- Unpaid set = the rule in `_parent_home_balance` (`composition/parent.py`): status in `CHARGEABLE_INVOICE_STATUSES` and `balance_due_cents > 0`. Extract that predicate into one function and call it from both, so Home and Payments can never disagree.
- `amount_due_cents` = sum of `balance_due_cents` over the unpaid set. `due_date` = earliest. `overdue` on the academy's date.
- `lines`: per unpaid invoice, positive invoice lines are summed onto the invoice's `student_id` (child line); negative lines are grouped by their stored description (discount or credit lines); `paid` = `total_cents − balance_due_cents`. Omit zero lines. An invoice with no `student_id` gets a child line labelled `Family`.
- Invariant, asserted in the use case and tested: `sum(lines.amount_cents) == amount_due_cents`. If one invoice's lines do not add up to its total (legacy shape), that invoice contributes a single child line equal to its balance and no discount line. A wrong breakdown is never returned.
- `periods`: last 12 periods with any non-void invoice.
- `can_pay_online`: the existing rule that decides whether the pay buttons show.
- No caching headers needed beyond the default; the service worker already treats `/api/*` as network-only. Query key `["parent","money-summary"]`, invalidated wherever `["parent","invoices"]` is.

### 7.2 Extended: `GET /api/v2/parent/invoices` and `/parent/payments`

- `ParentInvoiceView` gains `student_name: str | None`, `class_name: str | None`, `paid_on: date | None`, `method_label: str | None` (last allocation), `has_receipt: bool` (`status == "paid"`).
- `ParentPaymentView` gains `student_names: list[str]` (from the allocated invoices; empty when unallocated) and `method_label: str`. The frontend stops showing `stripe_*` ids.

### 7.3 New: `GET /api/v2/parent/invoices/{invoice_id}/receipt`

In `invoice_routes.py`. Uses `GetParentInvoice` (already alias-aware and tenant-scoped). Returns 404 when the invoice is not the caller's, is in another academy, or is not `paid`. Response: academy `{name, address, phone, email, logo_url}`, `invoice_number`, `period_label`, `payer_name`, `student_name`, `lines[{label, amount_cents}]`, `total_cents`, `payments[{paid_on, method, amount_cents}]`, `balance_cents`, `paid_in_full_on`. Method here is the bare word (`Cash`, `Card`, …).

### 7.4 Route bookkeeping for the new page

Add `/parent/payments/receipt/[invoiceId]` to `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` and bump the route count in `test_inventory_control_evidence.py` and `test_inventory_acceptance_coverage.py`; states list must include `loading`, `error`, `not found`.

## 8. Accessibility

- Summary card is a `<section aria-labelledby>`; the figure and date are one sentence for screen readers: `aria-label="You owe $150.00, due Tuesday, December 1"`.
- Lines are a `<dl>`; the discount amount reads "minus $30.00" (`aria-label`), not "dash".
- Overdue is conveyed by words and a chip, not colour alone.
- All buttons `min-h-touch`; Receipt and View detail are separate 44px targets with 8px between.
- Receipt: logical heading order (h1 academy, h2 Receipt); print button has visible text; print styles keep 12pt minimum.
- Focus moves to the summary heading after a successful payment return.

## 9. Out of scope

Next month's estimate; PDF generation or emailed receipts; a family statement across months; refunds UI; changing the pay flow, autopay, or the billing portal; per-child payment (the family pays invoices as today); Spanish (D-23).

## 10. Acceptance checklist (parent-busy, seed K09)

1. Payments opens with "YOU OWE $… / Due …" as the first thing on the screen at 375px, no scrolling.
2. Sam and Alex each have a line; "Sibling discount" is its own line; "Total for your family" equals the big figure and equals the amount on Home.
3. With nothing due, the card says "$0.00 · Nothing to pay right now."
4. October shows "PAID · Paid in cash · Oct 3" with Sam's name; the header reads "October 2026 · $… paid".
5. Payment history rows show a child name and "Paid in cash"; no row says "succeeded"; no Stripe ids.
6. Receipt opens, prints on one page with academy, child, amount, date and method, and nothing else from the app.
7. Editing the receipt URL to another family's invoice id shows "We could not open this receipt"; an unpaid invoice id does the same.
8. "Change or pause in Children" goes to Children.
9. Turn the network off and reload: an error with Retry, no stale figure.

## Build notes (S57/S58)

- Method words: Stripe checkout rows read `Paid online` (receipt word `Online`), not `Paid by card`. The ledger's `stripe_checkout` method covers card and bank debit (#433) and stores no instrument, so "card" would be wrong for ACH families.
