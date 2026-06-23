# Billing Health Admin UI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give admins a `/admin/billing-health` page that surfaces reconciliation-run history, open failed autopay payments (with one-click retry), and quarantined webhook events (with replay) — making the #224 app-owned billing infrastructure observable and actionable.

**Architecture:** Add thin read/query methods to two existing Mongo repos (reconciliation-run repo and ledger repo's payment_attempts), wire them plus a manual-reconcile trigger and a webhook-replay action into the existing admin `AdminUseCases` + `billing_routes.py` router (all tenant-scoped via `current_academy_id()`). On the frontend, build one new client page that mirrors the existing `payments/page.tsx` patterns (React Query + `apiFetch` + DS components), reusing the already-shipped `charge-autopay` and webhook-events endpoints where they exist.

**Tech Stack:** FastAPI, Motor/PyMongo, Pydantic v2, pytest (backend) · Next.js 15 App Router, React 19, TanStack React Query, Radix UI, Tailwind, Playwright (frontend).

**Spec:** `docs/superpowers/specs/2026-06-21-billing-health-admin-ui-design.md`
**Issue:** https://github.com/Ramc4685/academy-manager/issues/235

---

## Reconciliation: spec vs. actual codebase

These decisions override the spec where the codebase already provides something:

| Spec said | Reality | Decision |
|-----------|---------|----------|
| `POST /admin/billing/charge-invoice/{id}` (new) | `POST /admin/billing/invoices/{invoice_id}/charge-autopay` already exists (ChargeInvoiceViaAutopay) | **Reuse existing endpoint** — no new charge route |
| Quarantine via `recovery_point=quarantined` | `stripe_webhook_events.status == "quarantined"` (no `recovery_point` field); `error_message` holds the reason | Query/display by `status`, reason from `error_message` |
| Webhook events endpoint (new) | `listBillingWebhookEvents` + GET endpoint already exist and are used on payments page | **Reuse** for the quarantined list (filter `status=quarantined`); only the **replay** action is new |
| Nav in `frontend/app/(admin)/layout.tsx` | Nav defined in `frontend/components/admin/screen-meta.ts` (`ADMIN_NAV`, `SCREEN_META`) | Edit `screen-meta.ts` |
| Reconciliation runs read method exists | Repo is write-only (`record_run` only) | **Add `list_runs`** |
| Payment attempts read method exists | Repo is write-only (`record_payment_attempt` only) | **Add `list_payment_attempts`** |

**Net new endpoints (5):**
1. `GET /admin/billing/reconciliation-runs`
2. `POST /admin/billing/reconcile`
3. `GET /admin/billing/failed-payment-attempts`
4. `GET /admin/billing/invoices/{invoice_id}/attempts`
5. `POST /admin/billing/webhook-events/{event_id}/replay`

(Charge/retry and quarantined-events listing reuse existing endpoints.)

---

## File Structure

**Backend (create):** none — all additions go into existing files.
**Backend (modify):**
- `backend/v2/contexts/billing/infrastructure/mongo_billing_reconciliation_run_repo.py` — add `list_runs`
- `backend/v2/contexts/billing/infrastructure/mongo_billing_ledger_repo.py` — add `list_payment_attempts`, `list_open_failed_attempts`
- `backend/v2/contexts/billing/infrastructure/mongo_stripe_dedup.py` — add `replay` (reset quarantined → received)
- `backend/v2/interfaces/admin/<use-cases module>` (`AdminUseCases`) — add 5 use-case callables
- `backend/v2/interfaces/admin/billing_routes.py` — add 5 routes + Pydantic response DTOs
- `backend/v2/tests/interface/test_admin_billing.py` — add endpoint tests

**Frontend (create):**
- `frontend/app/(admin)/admin/billing-health/page.tsx` — the page
- `frontend/e2e/specs/billing-health.spec.ts` — e2e

**Frontend (modify):**
- `frontend/lib/api/admin.ts` — API functions + types
- `frontend/lib/query/keys.ts` — query keys
- `frontend/components/admin/screen-meta.ts` — nav entry + screen meta

---

## Chunk 1: Backend repository read methods

### Task 1: `list_runs` on reconciliation-run repo

**Files:**
- Modify: `backend/v2/contexts/billing/infrastructure/mongo_billing_reconciliation_run_repo.py`
- Test: `backend/v2/tests/infrastructure/test_billing_reconciliation_run_repo.py` (create if absent; otherwise extend existing repo test)

- [ ] **Step 1: Write failing test** — seed two runs (different `started_at`) for academy `acad`, one run for `other`; assert `list_runs("acad", limit=10)` returns only `acad` runs, newest `started_at` first, as plain dicts.
- [ ] **Step 2: Run test, verify it fails** (`AttributeError: list_runs`). Run: `cd backend && pytest v2/tests/infrastructure/test_billing_reconciliation_run_repo.py -v`
- [ ] **Step 3: Implement** `async def list_runs(self, academy_id: str, *, limit: int = 50) -> list[dict[str, Any]]` — `find({"academy_id": academy_id}).sort("started_at", -1).limit(limit)`, strip `_id`, return list.
- [ ] **Step 4: Run test, verify pass.**
- [ ] **Step 5: Commit** `feat(billing): add list_runs to reconciliation run repo`

### Task 2: `list_payment_attempts` + `list_open_failed_attempts` on ledger repo

**Files:**
- Modify: `backend/v2/contexts/billing/infrastructure/mongo_billing_ledger_repo.py`
- Test: extend the existing ledger repo test module (find it next to the repo's existing tests; mirror its fixture)

- [ ] **Step 1: Write failing tests:**
  - `list_payment_attempts(invoice_id)` returns that invoice's attempts (from `payment_attempts` collection), newest `created_at` first, tenant-scoped to `current_academy_id()`.
  - `list_open_failed_attempts()` returns one row per invoice whose `status in {open, partially_paid}` AND whose latest attempt `status in {failed, requires_action}`; excludes invoices with a later `succeeded` attempt and excludes `paid`/`void` invoices. Each row carries: `invoice_id, parent_id, period, total_cents, balance_due_cents, currency, latest_attempt_at, latest_decline_code, attempt_count`.
- [ ] **Step 2: Run tests, verify they fail.**
- [ ] **Step 3: Implement** both methods. Use `current_academy_id()` filter (mirror existing repo helpers). For `list_open_failed_attempts`: load candidate invoices by status, then for each load latest attempt; or aggregate. Keep it readable over clever — N is tiny (handful of subscribers). `parent_name` is NOT resolved here (route/use-case layer joins it if cheap; otherwise omit and let frontend show parent_id) — see Task 6 note.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** `feat(billing): add payment-attempt read methods to ledger repo`

### Task 3: `replay` on stripe dedup repo

**Files:**
- Modify: `backend/v2/contexts/billing/infrastructure/mongo_stripe_dedup.py`
- Test: `backend/v2/tests/infrastructure/test_mongo_stripe_dedup.py` (create/extend)

- [ ] **Step 1: Write failing test** — store an event, `mark_quarantined(event_id, "reason")`, call `replay(event_id)`, assert doc now has `status="received"`, `error_message=None`, `next_retry_at` set (not None), `retry_count=0`, `processing_locked_until=None`, `processor_id=None`.
- [ ] **Step 2: Run test, verify fail.**
- [ ] **Step 3: Implement** `async def replay(self, event_id: str) -> bool` — `update_many({"event_id": event_id, "status": "quarantined"}, {"$set": {status:"received", error_message:None, next_retry_at: now, retry_count:0, processing_locked_until:None, processor_id:None}})`; return `matched_count > 0`. Only acts on quarantined events (idempotent / safe).
- [ ] **Step 4: Run test, verify pass.**
- [ ] **Step 5: Commit** `feat(billing): add replay for quarantined webhook events`

---

## Chunk 2: Backend use-cases + routes

### Task 4: Wire 5 callables into `AdminUseCases`

**Files:**
- Modify: the module defining `AdminUseCases` and `get_admin_use_cases` (composition/deps layer that already builds `charge_invoice_via_autopay`)
- Test: covered via route tests in Task 6

- [ ] **Step 1:** Locate where `AdminUseCases` is assembled (same place `charge_invoice_via_autopay` is wired). Add fields/callables:
  - `list_reconciliation_runs() -> list[dict]` → `MongoBillingReconciliationRunRepository(db).list_runs(current_academy_id(), limit=10)`
  - `run_reconciliation() -> dict` → instantiate `ReconcileStripePaymentIntents(stripe=…, ledger=MongoBillingLedgerRepository(db), run_recorder=MongoBillingReconciliationRunRepository(db), academy_id=current_academy_id()).execute(limit=100)` (mirror main.py wiring; handle Stripe-unconfigured by raising RuntimeError like the existing autopay wiring)
  - `list_failed_payment_attempts() -> list[dict]` → ledger `list_open_failed_attempts()`
  - `list_invoice_attempts(invoice_id) -> list[dict]` → ledger `list_payment_attempts(invoice_id)` (raise ValueError "not found" if invoice not in tenant)
  - `replay_webhook_event(event_id) -> bool` → dedup `replay(event_id)` (raise ValueError "not found" if no match)
- [ ] **Step 2: Commit** `feat(admin): wire billing-health use cases`

### Task 5: Add response DTOs to `billing_routes.py`

**Files:** Modify: `backend/v2/interfaces/admin/billing_routes.py`

- [ ] **Step 1:** Add Pydantic models near existing DTOs:
  - `ReconciliationRunDto` (run_id, started_at, finished_at, scanned, repaired, skipped, quarantined, failed, errors: list[str])
  - `ReconciliationRunsResponse` (runs: list[ReconciliationRunDto])
  - `FailedPaymentRowDto` (invoice_id, parent_id, parent_name: str|None, period, total_cents, balance_due_cents, currency, latest_attempt_at, latest_decline_code: str|None, attempt_count)
  - `FailedPaymentsResponse` (rows: list[…])
  - `PaymentAttemptDto` (attempt_id, status, amount_cents, currency, stripe_payment_intent_id: str|None, failure_code: str|None, failure_message: str|None, created_at)
  - `InvoiceAttemptsResponse` (attempts: list[…])
  - `ReplayWebhookResponse` (replayed: bool, event_id: str)
- [ ] **Step 2: Commit** `feat(admin): add billing-health response DTOs`

### Task 6: Add 5 routes (TDD)

**Files:**
- Modify: `backend/v2/interfaces/admin/billing_routes.py`
- Test: `backend/v2/tests/interface/test_admin_billing.py`

Mirror existing route style: `Depends(require_persona("admin"))`, `Depends(get_admin_use_cases)`, map `ValueError("not found")`→404, `RuntimeError`→503.

- [ ] **Step 1: Write failing tests** (one per route), mirroring `test_list_payments_returns_recent` and overriding `admin_client.use_cases.<callable>`:
  - `GET /api/v2/admin/billing/reconciliation-runs` → 200, `runs` sorted desc, shape matches DTO.
  - `POST /api/v2/admin/billing/reconcile` → 200, returns run dict keys (scanned/repaired/quarantined…). 503 when use case raises RuntimeError (Stripe unconfigured).
  - `GET /api/v2/admin/billing/failed-payment-attempts` → 200, only open/partially_paid+failed rows; excludes paid.
  - `GET /api/v2/admin/billing/invoices/{id}/attempts` → 200 newest-first; 404 for unknown/other-tenant invoice.
  - `POST /api/v2/admin/billing/webhook-events/{id}/replay` → 200 `{replayed:true,event_id}`; 404 when replay returns False.
- [ ] **Step 2: Run tests, verify fail.** Run: `cd backend && pytest v2/tests/interface/test_admin_billing.py -v`
- [ ] **Step 3: Implement the 5 route handlers.** For `failed-payment-attempts`, resolve `parent_name` via the existing admin student/parent lookup if it's already available on `use_cases` cheaply; otherwise return `parent_name=None` (frontend falls back to `parent_id`). Keep retry/charge reusing the existing `charge-autopay` route — do NOT add a new one.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Run full billing test suite** `cd backend && pytest v2/tests/interface/test_admin_billing.py v2/tests/infrastructure -v`
- [ ] **Step 6: Commit** `feat(admin): add billing-health endpoints`

---

## Chunk 3: Frontend API layer

### Task 7: Types + API functions in `admin.ts`

**Files:** Modify: `frontend/lib/api/admin.ts`

- [ ] **Step 1:** Add interfaces mirroring the DTOs: `ReconciliationRun`, `ReconciliationRunResult`, `FailedPaymentRow`, `BillingPaymentAttempt`, plus reuse existing `BillingWebhookEvent`.
- [ ] **Step 2:** Add functions (style: `apiFetch<…>("/admin/...", {method})`):
  - `fetchReconciliationRuns(): Promise<{runs: ReconciliationRun[]}>` → GET `/admin/billing/reconciliation-runs`
  - `triggerReconciliation(): Promise<ReconciliationRunResult>` → POST `/admin/billing/reconcile`
  - `fetchFailedPaymentAttempts(): Promise<{rows: FailedPaymentRow[]}>` → GET `/admin/billing/failed-payment-attempts`
  - `fetchInvoiceAttempts(invoiceId): Promise<{attempts: BillingPaymentAttempt[]}>` → GET `/admin/billing/invoices/{id}/attempts`
  - `replayWebhookEvent(eventId): Promise<{replayed:boolean; event_id:string}>` → POST `/admin/billing/webhook-events/{id}/replay`
  - Retry reuses **existing** `chargeInvoiceViaAutopay` (find current export name for the `charge-autopay` call; if absent, add it pointing at the existing route). Quarantined list reuses existing `listBillingWebhookEvents({status:"quarantined"})` — add `status` param if the function doesn't accept it.
- [ ] **Step 3: Typecheck** `cd frontend && npx tsc --noEmit` (expect clean).
- [ ] **Step 4: Commit** `feat(admin-ui): billing-health api client`

### Task 8: Query keys

**Files:** Modify: `frontend/lib/query/keys.ts`

- [ ] **Step 1:** Add under `admin`:
  ```ts
  reconciliationRuns: () => ["admin", "billing", "reconciliation-runs"] as const,
  failedAttempts: () => ["admin", "billing", "failed-attempts"] as const,
  quarantinedEvents: () => ["admin", "billing", "quarantined-events"] as const,
  invoiceAttempts: (invoiceId: string) => ["admin", "billing", "invoice-attempts", invoiceId] as const,
  ```
- [ ] **Step 2: Commit** `feat(admin-ui): billing-health query keys`

---

## Chunk 4: Frontend page + nav

### Task 9: Billing Health page

**Files:** Create: `frontend/app/(admin)/admin/billing-health/page.tsx`

Mirror `payments/page.tsx`: `"use client"`, DS imports (`Card`, `Button`, `Chip`, `BigNum`, `Overline`), React Query, custom inline `Metric`/`Alert`/table helpers.

- [ ] **Step 1:** Header (title, "Last reconciliation run: N min ago" from newest run `finished_at`, healthy/needs-attention pill, "Run reconciliation now" button → `useMutation(triggerReconciliation)` invalidating all four queries).
- [ ] **Step 2:** 4 stat cards (Last Run Scanned, Repaired [green], Open Failed Payments [red], Quarantined Events [yellow]).
- [ ] **Step 3:** Section 1 Reconciliation Runs table (last 10; columns Time/Scanned/Repaired/Skipped/Quarantined/Notes; row status dot; `refetchInterval: 30_000`).
- [ ] **Step 4:** Section 2 Open Failed Payments table (Parent·Invoice / Amount / Last attempt / Decline reason / Actions). Retry → `useMutation(chargeInvoiceViaAutopay)` with inline success/error; View → opens attempts panel.
- [ ] **Step 5:** Section 3 Quarantined Events table (Event ID / Type / Reason=`error_message` / Replay). Replay → `useMutation(replayWebhookEvent)` inline "Replayed — processing".
- [ ] **Step 6:** Invoice attempts panel (Radix Dialog, mirror `RallyDialog`) — chronological newest-first, status dot, ts, label, PI id (truncated), amount, failure message; empty state.
- [ ] **Step 7:** Empty/error states per spec table.
- [ ] **Step 8: Typecheck + lint** `cd frontend && npx tsc --noEmit`
- [ ] **Step 9: Commit** `feat(admin-ui): billing health page`

### Task 10: Navigation entry + screen meta

**Files:** Modify: `frontend/components/admin/screen-meta.ts`

- [ ] **Step 1:** Add to `ADMIN_NAV` MONEY group after Payments: `{ href: "/admin/billing-health", label: "Billing Health", icon: <existing icon key>, match: startsWith("/admin/billing-health") }`. Add matching `SCREEN_META` entry (title/subtitle) following siblings. (Live red-dot badge driven by failed/quarantined counts is OPTIONAL — only wire if the nav supports async counts without a new fetch on every page; otherwise defer and note in PR.)
- [ ] **Step 2: Typecheck.**
- [ ] **Step 3: Commit** `feat(admin-ui): add Billing Health to admin nav`

---

## Chunk 5: E2E + finalize

### Task 11: E2E spec

**Files:** Create: `frontend/e2e/specs/billing-health.spec.ts`

Mirror `billing-trust-recovery.spec.ts`: `stubMe(ADMIN_USER_A)`, `stubMemberships`, `page.route("**/api/v2/admin/billing/...", fulfillJson(...))`.

- [ ] **Step 1:** Stub all four GET endpoints + the reconcile/charge/replay POSTs; navigate to `/admin/billing-health`; assert 3 sections render, stat cards show seeded counts.
- [ ] **Step 2:** Click "Run reconciliation now" → assert POST fired and a new run row appears.
- [ ] **Step 3:** Click Retry on a failed row → assert charge-autopay POST fired, inline result shown.
- [ ] **Step 4:** Click View → → assert attempts panel opens with seeded attempts.
- [ ] **Step 5: Run** `cd frontend && npx playwright test e2e/specs/billing-health.spec.ts` (skip if local port busy — note in PR).
- [ ] **Step 6: Commit** `test(e2e): billing health page`

### Task 12: Full verification + PR

- [ ] **Step 1:** Backend: `cd backend && pytest v2/tests/interface v2/tests/infrastructure -q`
- [ ] **Step 2:** Frontend: `cd frontend && npx tsc --noEmit`
- [ ] **Step 3:** Update `docs/architecture/generated/08-billing-stripe-flow.md` if it references admin observability (optional; note if skipped).
- [ ] **Step 4:** Push branch, open PR referencing #235 and #224. Do NOT merge.

---

## Notes
- Every new query/route is tenant-scoped through `current_academy_id()` — verify each read filters by academy.
- No new charge route: retry reuses `POST /admin/billing/invoices/{invoice_id}/charge-autopay`.
- Keep `list_open_failed_attempts` simple (small N). Optimize only if needed.
