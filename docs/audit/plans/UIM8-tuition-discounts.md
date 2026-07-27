# UIM8 — Tuition-discounts report UI
Status: DONE (PR #359, 2026-07-26)
Size: S · Depends on: UIC3 (target surface — merged Reports) · Tracker: ../TRACKER.md

Note: UIC3 had not actually merged at implementation time (TRACKER still
listed it TODO), so per this plan's own fallback the Discounts section was
built on the existing `/admin/dues` page instead of the Reports surface.
Move it into Reports once UIC3 lands.

## User value
Admins granting tuition discounts today have no way to see their aggregate cost. A per-period discounts table (gross tuition vs discounts vs net, broken down by category) makes discounting a visible, reviewable finance lever instead of an invisible leak.

## Backend status (verified)
- `GET /admin/finance/tuition-discounts?period=YYYY-MM` exists and is dark (zero frontend callers): `backend/v2/interfaces/admin/billing_routes.py:717` (`tuition_discount_summary`), persona-gated with `require_persona("admin")`.
- Response DTO `AdminTuitionDiscountSummaryResponse` (`backend/v2/interfaces/admin/views.py:1216`):
  - `period: str`
  - `gross_tuition_cents: int`
  - `discount_cents: int`
  - `net_tuition_cents: int`
  - `by_category: [{ category: str, discount_cents: int }]` (sorted by descending amount)
- Query implementation `MongoTuitionDiscountSummaryQuery` (`backend/v2/contexts/billing/application/use_cases/finance.py:79`) aggregates non-void invoices for the period from `invoice_lines` (tenant-scoped). `period` is required; 503 if the use case is not wired.

## Frontend to build
Per UIC3, session economics + dues are being merged into `admin/reports`; this table belongs on that merged Reports surface (a "Discounts" section/tab alongside dues/revenue). If UIC3 has not landed yet, build it on the existing dues page and note the move in UIC3's plan — do not create a new standalone page.

- Month picker (`YYYY-MM`, default current period) shared with the dues/reports period selector if one exists.
- Summary strip: gross tuition, total discounts, net tuition (cents → currency formatting consistent with existing finance pages).
- Table: category · discount amount · % of gross. Empty state when `by_category` is empty.
- Data layer: `apiFetch` wrapper in `frontend/lib/api/v2/` (new `getTuitionDiscountSummary(period)`), TanStack Query v5 `useQuery`, query key added to `frontend/lib/query/keys.ts` under `admin.*`, e.g. `tuitionDiscounts: (period: string) => ["admin", "tuition-discounts", period]`.

## Backend to build (if any)
None. Route, DTO, and tenant-scoped query already exist.

## Implementation steps
1. Add API client function + typed response interface mirroring the DTO above.
2. Add query key to `lib/query/keys.ts`.
3. Add the Discounts section to the merged Reports surface (or dues page pre-UIC3) with period picker, summary strip, table, loading/empty/error states (typed `ApiError` → `role="alert"` banner, matching existing pattern).
4. Wire the period picker to the query; keep the selected period in the URL search params so it is linkable.

## Files to change/create
- `frontend/lib/api/v2/finance.ts` (or nearest existing admin billing client module) — add fetcher + types.
- `frontend/lib/query/keys.ts` — add key.
- `frontend/app/(admin)/admin/reports/page.tsx` (post-UIC3) or `frontend/app/(admin)/admin/dues/page.tsx` (pre-UIC3) — add section.

## Verification
- Unit: none needed backend-side. Frontend: type-check + lint.
- Manual/e2e: seed a period with tuition lines + a `tuition_discount` line; verify gross/discount/net math and category rows render; verify empty period renders empty state, not 0-division NaN for the % column.
- Confirm route still passes `backend/v2/tests/unit/test_audit_inventory_manifest.py` untouched (no backend change).

## Risks / rollback
- Purely additive frontend; rollback = revert the PR.
- Coordination risk with UIC3 only (surface location). If both are in flight, land UIC3 first.

## PR checklist
- [ ] Release note line
- [ ] TRACKER.md row updated (Status, PR/Issue)
- [ ] This plan's Status → DONE (PR #NNN, date)
