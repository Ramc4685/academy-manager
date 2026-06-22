# Billing Health Admin UI — Design Spec

**Date:** 2026-06-21
**Depends on:** #224 (app-owned billing / Stripe processor-only)
**Status:** Approved for implementation

---

## Problem

Issue #224 added backend infrastructure for billing reconciliation and payment attempt tracking, but none of it is visible to admins:

- `billing_reconciliation_runs` collection stores run summaries (scanned/repaired/quarantined/errors) — no UI
- `payment_attempts` stored on LedgerInvoice for every charge outcome — no UI
- Quarantined webhook events stored in `stripe_webhook_events` with `recovery_point=quarantined` — no replay UI

Admins cannot see whether the 10-minute reconciliation scheduler is healthy, which invoices have failed payment attempts, or which webhook events need manual review.

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where does billing health live? | Dedicated `/admin/billing-health` page | Separation of concerns; room to grow as subscriber count increases |
| Payment attempt history placement | Summary of unresolved failures on Health page + full timeline on invoice detail | Health page = "what needs action now"; invoice detail = "what happened to this invoice" |
| What the Health page filters | Open failed payments only (no successful payment yet) | Excludes resolved invoices; keeps the page actionable |
| Quarantine replay | Single "Replay" button per event; re-enqueues event for processing | Admin fixes data mismatch then replays |

---

## Pages and Components

### 1. `/admin/billing-health` — New Page

**File:** `frontend/app/(admin)/admin/billing-health/page.tsx`

#### Page header
- Title: "Billing Health"
- Subtitle: "Last reconciliation run: {N} min ago" (derived from most recent run's `finished_at`)
- Status pill: green "● System healthy" when no open failed payments and no quarantined events; red "● Needs attention" otherwise
- Button: "Run reconciliation now" — calls `POST /api/v2/admin/billing/reconcile` and invalidates all queries

#### Stat cards (4-column row)

| Card | Source field | Accent when non-zero |
|------|-------------|----------------------|
| Last Run Scanned | `scanned` | neutral |
| Repaired | `repaired` | green |
| Open Failed Payments | count from failed-attempts endpoint | red |
| Quarantined Events | count from quarantined-events endpoint | yellow |

#### Section 1 — Reconciliation Runs

- Table of last 10 runs from `GET /api/v2/admin/billing/reconciliation-runs`
- Columns: Time, Scanned, Repaired, Skipped, Quarantined, Notes
- Row status icon: ● green (quarantined=0, repaired=0) · ⚠ yellow (repaired>0) · ✗ red (quarantined>0 or failed>0)
- Notes column: first error from `errors[]` array, truncated at 80 chars
- Auto-refreshes every 30s via React Query `refetchInterval`

#### Section 2 — Open Failed Payments

- Only invoices in `open` or `partially_paid` status where latest attempt has `status=failed` or `status=requires_action`
- Data from `GET /api/v2/admin/billing/failed-payment-attempts`
- Columns: Parent · Invoice, Amount, Last attempt (timestamp), Decline reason (`decline_code`), Actions
- Actions:
  - **Retry** — `POST /api/v2/admin/billing/charge-invoice/{invoice_id}` — runs `ChargeInvoiceViaAutopay`; show inline success/error result
  - **View →** — opens invoice attempt timeline panel (see Section 2 below)

#### Section 3 — Quarantined Webhook Events

- Events where `recovery_point = "quarantined"` in `stripe_webhook_events`
- Data from `GET /api/v2/admin/billing/quarantined-events`
- Columns: Event ID (truncated), Type, Reason quarantined (`last_error`), Action
- Action: **Replay** — `POST /api/v2/admin/billing/replay-webhook/{event_id}` — resets event to `status=received` so drain job picks it up; show inline confirmation

---

### 2. Invoice Attempt Timeline — Enhancement to Payments Page

**File:** `frontend/app/(admin)/admin/payments/page.tsx` (existing)

Add a payment attempts panel that opens when admin clicks **View →** on any invoice row.

- Data from `GET /api/v2/admin/billing/invoice/{invoice_id}/attempts`
- Chronological list, newest first
- Each row: status dot (green=succeeded · red=failed · yellow=requires_action), timestamp, status label, Stripe PI ID (truncated, links to Stripe dashboard), amount, failure message
- Empty state: "No payment attempts recorded for this invoice"

---

## Backend API — New Endpoints

All added to `backend/v2/interfaces/admin/billing_routes.py`. All endpoints are tenant-scoped (enforce `current_academy_id()`). Return 403 if academy mismatch.

### `GET /admin/billing/reconciliation-runs`
Last 10 runs from `billing_reconciliation_runs`, sorted `started_at` desc.

Response item shape:
```json
{
  "run_id": "01HX...",
  "academy_id": "acad_xxx",
  "started_at": "2026-06-21T10:02:00Z",
  "finished_at": "2026-06-21T10:02:01Z",
  "scanned": 8,
  "repaired": 0,
  "skipped": 8,
  "quarantined": 0,
  "failed": 0,
  "errors": []
}
```

### `POST /admin/billing/reconcile`
Triggers `ReconcileStripePaymentIntents(academy_id=current_academy_id()).execute(limit=100)` immediately.
Returns the run result dict. Idempotent — safe to call multiple times.

### `GET /admin/billing/failed-payment-attempts`
Invoices in `open` or `partially_paid` status where latest `payment_attempt.status` is `failed` or `requires_action`. Tenant-scoped via `current_academy_id()`.

Response item shape:
```json
{
  "invoice_id": "inv_xxx",
  "parent_id": "parent_xxx",
  "parent_name": "Sarah M.",
  "period": "2026-06",
  "total_cents": 12000,
  "balance_due_cents": 12000,
  "currency": "usd",
  "latest_attempt_at": "2026-06-21T09:45:00Z",
  "latest_decline_code": "card_declined",
  "attempt_count": 2
}
```

### `POST /admin/billing/charge-invoice/{invoice_id}`
Calls `ChargeInvoiceViaAutopay.execute(invoice_id)`. Validates invoice belongs to `current_academy_id()` before charging. Returns `ChargeResult`.

### `GET /admin/billing/quarantined-events`
Events from `stripe_webhook_events` where `recovery_point = "quarantined"`, sorted `received_at` desc, limit 50. Tenant-scoped.

Response item shape:
```json
{
  "event_id": "evt_1Abc...",
  "event_type": "payment_intent.succeeded",
  "received_at": "2026-06-21T09:42:00Z",
  "last_error": "parent mismatch: invoice=parent_A payment_intent=parent_B",
  "retry_count": 3
}
```

### `POST /admin/billing/replay-webhook/{event_id}`
Resets the event: `status=received`, `recovery_point=null`, `retry_count=0`, `next_retry_at=now`. Validates event belongs to `current_academy_id()`. Returns `{"replayed": true, "event_id": "..."}`.

### `GET /admin/billing/invoice/{invoice_id}/attempts`
Returns `payment_attempts` array from the LedgerInvoice document, sorted newest first. Validates invoice belongs to `current_academy_id()`.

Response item shape:
```json
{
  "attempt_id": "attempt_xxx",
  "status": "failed",
  "amount_cents": 12000,
  "currency": "usd",
  "stripe_payment_intent_id": "pi_3Abc...",
  "failure_code": "card_declined",
  "failure_message": "Your card was declined.",
  "created_at": "2026-06-21T09:45:00Z"
}
```

---

## Frontend Tech Stack

- **Framework:** Next.js 15 App Router, React 19
- **Data fetching:** TanStack React Query — add keys to `frontend/lib/query/keys.ts`
- **API client:** add functions to `frontend/lib/api/admin.ts`
- **UI:** Tailwind; Radix UI for any overlay panels; match existing admin page patterns in `frontend/app/(admin)/admin/payments/page.tsx`
- **Polling:** `refetchInterval: 30_000` on reconciliation runs query only

### New React Query keys (`frontend/lib/query/keys.ts`)
```typescript
billing: {
  reconciliationRuns: () => ['admin', 'billing', 'reconciliation-runs'] as const,
  failedAttempts: () => ['admin', 'billing', 'failed-attempts'] as const,
  quarantinedEvents: () => ['admin', 'billing', 'quarantined-events'] as const,
  invoiceAttempts: (invoiceId: string) => ['admin', 'billing', 'invoice-attempts', invoiceId] as const,
}
```

### New admin API functions (`frontend/lib/api/admin.ts`)
```typescript
fetchReconciliationRuns(): Promise<ReconciliationRun[]>
triggerReconciliation(): Promise<ReconciliationRunResult>
fetchFailedPaymentAttempts(): Promise<FailedPaymentRow[]>
chargeInvoice(invoiceId: string): Promise<ChargeResult>
fetchQuarantinedEvents(): Promise<QuarantinedEvent[]>
replayWebhookEvent(eventId: string): Promise<{replayed: boolean; event_id: string}>
fetchInvoiceAttempts(invoiceId: string): Promise<PaymentAttempt[]>
```

---

## Navigation

**File:** `frontend/app/(admin)/layout.tsx`

Add "Billing Health" nav entry after the existing Payments link:
- Route: `/admin/billing-health`
- Label: `Billing Health`
- Show a red dot badge when `failedAttempts.length > 0 || quarantinedEvents.length > 0`

---

## Error and Empty States

| State | Display |
|-------|---------|
| No reconciliation runs yet | "No runs recorded yet. The scheduler runs every 10 minutes." |
| No failed payments | ✓ "All autopay invoices are current." (green) |
| No quarantined events | ✓ "No quarantined webhook events." (green) |
| Retry succeeds | Replace row with "Charged successfully" then remove from list |
| Retry fails | Inline error under row: `{decline_code} — {failure_message}` |
| Replay submitted | Replace button with "Replayed — processing" |
| Page API error | Standard error boundary with "Retry" button |

---

## Testing Requirements

### Backend — `v2/tests/interface/test_admin_billing.py`
- `GET /admin/billing/reconciliation-runs` returns last 10 sorted desc; tenant isolation (wrong academy → empty list)
- `POST /admin/billing/reconcile` returns run result dict with expected keys
- `GET /admin/billing/failed-payment-attempts` only returns open/partially_paid invoices with failed last attempt; excludes paid invoices
- `POST /admin/billing/charge-invoice/{id}` calls `ChargeInvoiceViaAutopay`; returns 404 for wrong academy invoice
- `GET /admin/billing/quarantined-events` only returns `recovery_point=quarantined` events; tenant-scoped
- `POST /admin/billing/replay-webhook/{id}` resets event fields; returns 404 for wrong academy event
- `GET /admin/billing/invoice/{id}/attempts` returns attempts newest-first; returns 404 for wrong academy invoice

### Frontend — `frontend/e2e/specs/billing-trust-recovery.spec.ts` (extend existing)
- Health page loads with all 3 sections visible
- "Run reconciliation now" button fires and new run appears in list
- Failed payment row shows Retry button; clicking shows result
- Invoice attempt timeline appears on "View →" click

---

## Out of Scope

- Email/push alerts when quarantine count rises
- Bulk replay of quarantined events
- Pagination on reconciliation runs (limit=10 sufficient for now)
- Parent-facing "payment failed" notification
- Historical chart of repaired/quarantined counts over time
