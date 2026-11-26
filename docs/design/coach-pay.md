# Coach pay: coach-scoped read (S59) and Pay page (S60)

Decision applied: **D-05 option 3**. A coach sees the classes they taught and their payslips once approved or paid. Never a draft. Never the revenue figure behind a percentage rate. This replaces the "coaches see nothing about pay" row in `docs/security-matrix.md` with "Self only".

## 1. Goal and the quotes it answers

A coach can answer "how many classes did I teach this month, and what was I paid?" without texting the owner.

- coach-veteran: "I cannot find my hours or my pay anywhere… every payroll page I tried is a 404."
- coach-veteran: "Add a 'My hours and pay' screen (this month hours, rate, expected pay, past payslips)."
- coach-new: "…nothing about how or when I get paid."
- coach-new: "A pay page with my hours, rate and next payday."

"Rate", "expected pay" and "next payday" are deliberately not shown: see section 9.

## 2. Entry points and navigation

- Coach **Profile** (`/coach/profile`): a new row "Pay · Classes taught and payslips →" above the account section, 44px, full width.
- New route `/coach/profile/pay`. Back link "← Profile". The Profile bottom tab stays active (`pathname.startsWith("/coach/profile")` already covers it).
- No bottom-tab entry and no link from Today.

## 3. Layout

### 3.1 Phone (375px)

```
┌───────────────────────────────────────┐
│ ← Profile                             │
│ Pay                                   │  h1
│ ┌───────────────────────────────────┐ │
│ │  ‹   November 2026   ›            │ │  month stepper, 44px arrows
│ ├───────────────────────────────────┤ │
│ │ CLASSES TAUGHT        TIME        │ │  two Scoreboard stats
│ │ 8                     9 h 30 min  │ │  BigNum 32px
│ └───────────────────────────────────┘ │
│                                       │
│ ━━ PAYSLIP ━━━━━━━━━━━━━━━━━━━━━━━━━━ │  LaneHeader
│ ┌───────────────────────────────────┐ │
│ │ Nov 1 – Nov 30         ● APPROVED │ │  Chip approved / paid
│ │ $380.00                           │ │  BigNum 28px
│ │ Approved Dec 2. Not paid yet.     │ │
│ └───────────────────────────────────┘ │
│   — or, when none is approved —       │
│ │ No payslip for November yet.      │ │
│ │ It appears here once the academy  │ │
│ │ approves it.                      │ │
│                                       │
│ ━━ CLASSES ━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│ Sat, Nov 28 · 9:00 AM                 │  PhoneList rows
│ Junior Beginners · 60 min      Lead   │
│ ─────────────────────────────────────│
│ Tue, Nov 24 · 5:30 PM                 │
│ Tuesday Intermediate · 60 min  Cover  │
│ ─────────────────────────────────────│
│ Sat, Nov 21 · 9:00 AM                 │
│ Junior Beginners · 60 min  Assistant  │
│                                       │
│ ━━ HOW YOU ARE PAID ━━━━━━━━━━━━━━━━━ │
│ Demo Academy works out pay after the  │
│ month ends. Your payslip appears here │
│ when the academy approves it, and is  │
│ marked Paid when they have paid you.  │
│ Questions about your pay? Call        │
│ (309) 555-0142 or email               │
│ hello@demo.test.                      │  ContactLinks
└───────────────────────────────────────┘
```

### 3.2 Desktop (≥1024px)

The coach shell is a single column on every width. Constrain to `max-w-xl`. Stats sit side by side; the class list becomes a three-column grid row (date and time, class and minutes, role) without a table header.

### 3.3 Paid payslip

```
│ │ Oct 1 – Oct 31             ● PAID │
│ │ $420.00                           │
│ │ Paid Nov 3 by bank transfer.      │
```

## 4. States

| State | What the coach sees |
|---|---|
| Loading | Month stepper enabled; stats, payslip and list as `Skeleton` (two blocks and four lines). |
| Empty month (no classes) | Stats "0" and "0 min". Class list: `EmptyState` title "No classes taught in November", description "Classes you teach appear here after they finish." |
| No approved payslip | The "No payslip for {month} yet" text in section 3.1. Identical whether a draft exists or not, so the screen never reveals a draft. |
| Approved | Chip `APPROVED`, total, "Approved {date}. Not paid yet." |
| Paid | Chip `PAID`, the paid amount, "Paid {date} by {method}." |
| Paid amount differs from total | Extra line: "Payslip total $420.00, paid $400.00. Ask the academy about the difference." |
| Error | `ErrorNotice` "We could not load your pay. Check your connection and try again." with Retry. No cached figures: nothing is shown offline. |
| Offline | Same error text plus "Pay is only available online." (This read is never stored on the device.) |
| Admin or owner viewing the coach surface | The same page for their own user id, normally empty. They are never shown another coach's pay here; the admin Payouts screen is the place for that. |

## 5. Exact copy

- Page title `Pay`. Profile row: `Pay` with sub-line `Classes taught and payslips`.
- Stats: `CLASSES TAUGHT`, `TIME`. Time format: `9 h 30 min`; under one hour `45 min`.
- Role words on class rows: `Lead`, `Cover`, `Assistant` (from the line basis: scheduled or actual → Lead; substitute → Cover; assistant → Assistant).
- Payslip lane title `Payslip`; chips `APPROVED`, `PAID`.
- How-you-are-paid paragraph: exactly as in 3.1, with the academy name, phone and email substituted. If the academy has no phone or email, the last sentence is "Questions about your pay? Ask the academy owner."
- Month stepper labels: `Previous month`, `Next month` (aria). Next is disabled on the current month.
- Words: "class" and "class date"; never "session", "occurrence", "payout period" or "draft".

## 6. Components

Reuse from `frontend/components/ds/`: `Card`, `BigNum`, `Overline`, `LaneHeader`, `Chip` (`approved`, `paid`), `PhoneList`/`PhoneListRow`, `Skeleton`, `EmptyState`, `ErrorNotice`, `ContactLinks`, `Button` (ghost, for the stepper arrows). Dates through `formatAcademyDate` / `formatAcademyClock` (`frontend/lib/format/academy-time.ts`). Money through `formatCents` (`frontend/lib/money`).

New: none beyond the page file `frontend/app/(coach)/coach/profile/pay/page.tsx` and one API function `getCoachPay(month?)` in `frontend/lib/api/coach.ts`.

## 7. Data

### 7.1 New: `GET /api/v2/coach/profile/pay?month=YYYY-MM`

- Module: `backend/v2/interfaces/coach/profile_routes.py`; use case `contexts/finance/application/use_cases/coach_pay_summary.py`; wiring `composition/coach_pay.py`.
- Auth: `require_coach_surface()`. The coach id is **always** `claims.user_id`. There is no `coach_id` parameter of any kind, so there is nothing to tamper with. Tenant = request academy.
- `month` defaults to the current month on the academy clock. Accept the current month and the previous 23; anything else is 422.
- Path is outside the service worker's `COACH_API` matcher (`/api/v2/coach/(today|sessions)`), so it falls to NetworkOnly. Response sets `Cache-Control: no-store`.

```json
{
  "month": "2026-11",
  "month_label": "November 2026",
  "classes_taught": 8,
  "minutes_taught": 570,
  "classes": [
    {"occurrence_id": "…", "start_at": "2026-11-28T15:00:00Z", "class_name": "Junior Beginners", "minutes": 60, "role": "lead"}
  ],
  "payslip": {
    "period_start": "2026-11-01", "period_end": "2026-11-30",
    "status": "approved",
    "total_cents": 38000, "currency": "usd",
    "approved_on": "2026-12-02",
    "paid_on": null, "paid_method_label": null, "paid_amount_cents": null
  },
  "academy_contact": {"name": "Demo Academy", "phone": "(309) 555-0142", "email": "hello@demo.test"}
}
```

Rules:
- `classes`: class dates in the month that count as **held** under the S36 definition (`contexts/finance/application/reporting_definitions.py`) and where this coach is the lead who taught (actual coach, else substitute, else scheduled) or a listed assistant. Cancelled class dates are excluded. Newest first.
- `payslip`: the `PayoutPeriod` for this coach whose window covers the month, **only if** `status in {"approved","paid"}`; otherwise `null`. A draft returns `null`, exactly as if no period existed. If more than one approved or paid period overlaps the month, return the latest by `period_start` (shortcut: one payslip per month is the only shape the product creates today).
- Never serialised, for any rate type: `lines[].amount_minor`, `rate_id`, `percent_bps`, `expected_revenue_minor`, `original_amount_minor`, `adjustment_reason`, `unpaid_occurrences`, `payout_warnings`, `revenue_basis`, `paid_reference`. The view model is a fresh narrow DTO, not `PayoutPeriod` with fields dropped. Per-class amounts are withheld because a coach who knows their percentage could divide a class amount back into what families paid.
- `paid_method_label`: plain words from `paid_method` (`bank transfer`, `cash`, `check`, `other`).
- `academy_contact`: the same fields S16 adds to the coach academy read.
- Add the row to `docs/security-matrix.md`: "View own classes taught and approved or paid payslips | Admin: own only on this route | Coach: Self only | Parent: No", with the test file name.

### 7.2 Frontend caching

- Query key `["coach", "pay", month]`.
- Add `if (queryKey[1] === "pay") return false;` to `shouldPersistQuery` in `frontend/lib/query/persistence.ts`, with a test beside the existing exclusions.
- `gcTime: 0`, `staleTime: 0` on the query so leaving the page drops the figures from memory.
- Add a `sw.ts` test that `/api/v2/coach/profile/pay` is not matched by `COACH_API`.

### 7.3 Route bookkeeping

New route `/coach/profile/pay`: manifest entry in `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` (role `coach`; states `loading`, `empty`, `error`) and the two hard-coded route counts.

## 8. Accessibility

- The month stepper is a group with `aria-label="Month"`; the month name is an `aria-live="polite"` region so a screen reader hears the new month after a tap.
- Stats are `<dl>`; time reads "9 hours 30 minutes".
- Chips carry a dot and a word (status never by colour alone).
- Class rows are a list; the role word is text, not an icon.
- All targets 44px; contact links are real `tel:` and `mailto:` links from `ContactLinks`.
- Focus lands on the h1 when the page opens.

## 9. Out of scope

- The coach's rate, a pay estimate for an unapproved month, or a "next payday" date (no such setting exists; an estimate would be a draft by another name).
- Per-class pay amounts (see 7.1).
- Payment details capture (bank, Zelle handle) and availability: specified in `coach-home.md` section 9, not built.
- Downloadable payslip, tax forms, disputes or "this looks wrong" requests in the app.
- Any change to how payouts are generated, approved or paid.

## 10. Acceptance checklist

coach-veteran (seed K15: approved October payslip, draft November):
1. Profile shows a "Pay" row; it opens `/coach/profile/pay`.
2. November lists the classes taught with dates, minutes and Lead/Cover/Assistant, and the totals match the list.
3. November shows "No payslip for November yet"; no amount and no hint that a draft exists.
4. Step back to October: "APPROVED", the total, and the approval date.
5. No rate, percentage, family payment or per-class amount appears anywhere, including in the network response.
6. Reload offline: the error text, no figures.

coach-new:
7. Guessing `/api/v2/coach/profile/pay?coach_id=<another coach>` returns her own data; there is no URL that returns another coach's pay.
8. `/coach/payroll`, `/coach/pay` still 404 (only `/coach/profile/pay` exists).
9. The "How you are paid" paragraph names the academy and gives a number she can call.
