# UIC4 — Coach payslip → tab of /admin/payouts
Status: DONE (PR #346, 2026-07-24)
Size: S · Depends on: none · Tracker: ../TRACKER.md

## Problem
`/admin/coach-payslip` (109L) is a separate MONEY nav item that just re-shapes payout data per coach (card grid of net earnings). `/admin/payouts` (187L "Coach Payroll") is the operational surface for the same data. Two nav items, one domain.

## Current behavior (verified)
- `app/(admin)/admin/coach-payslip/page.tsx`: joins `listAdminUsers("coach")` × `listPayouts` (`lib/api/admin`), renders per-coach cards (net earnings, rule label, sessions/students counts, PAID/DRAFT chip). Read-only. `data-testid="admin-coach-payslip"`. Query keys `["admin","users","coach"]`, `["admin","finance","payouts","coach-payslip"]`.
- `app/(admin)/admin/payouts/page.tsx`: month-scoped payroll (`listMonthlyPayroll(month)` from `lib/api/v2/payroll`), bulk generate/recompute/export, `MonthPicker` in `payouts/_components/`, warning banner, navigates to detail `payouts/[payoutId]`. `data-testid="admin-payouts"`. **No tab pattern yet.**
- Nav: `screen-meta.ts:77` (Coach payouts), `:78` (Coach payslip). Meta `:124-125`.
- e2e: `admin-shell.spec.ts:84` visits `/admin/coach-payslip` expecting `admin-coach-payslip` testid.

## Proposed change (target IA)
`/admin/payouts` gets a small two-tab header (pattern copied from `admin/requests/page.tsx:69-92` tablist pills): **Payroll** (existing page body, default) · **Payslips** (moved card grid). Deep link `?tab=payslips`. `/admin/coach-payslip` redirects there. Nav item removed. (Tab, not drawer: payslip is an all-coaches overview, not a per-row detail — a drawer would need a coach picker anyway.)

## Implementation steps
1. Extract the payslip page body (rows join, card grid, `Skeleton`) into `app/(admin)/admin/payouts/_components/PayslipsPanel.tsx`, keeping query keys and `data-testid="admin-coach-payslip"` on the panel root.
2. In `payouts/page.tsx`: add `type PayoutsTab = "payroll" | "payslips"`, a pill tablist (reuse the `role="tablist"`/`aria-selected` markup from requests page), init from `useSearchParams().get("tab")`. Render existing content for `payroll`, `<PayslipsPanel />` for `payslips`. Keep the `MonthPicker` in the payroll tab only (payslip data is not month-scoped today — `listPayouts` takes no period).
3. Replace `app/(admin)/admin/coach-payslip/page.tsx` with `redirect("/admin/payouts?tab=payslips")`.
4. `screen-meta.ts`: delete nav item `:78` and `SCREEN_META["/admin/coach-payslip"]` (`:125`); optionally retitle `:77`/`:124` to "Payroll & payouts".
5. e2e: update `admin-shell.spec.ts:84` row to assert redirect (or new URL) and that `admin-coach-payslip` testid renders on the Payslips tab. No network stub changes (`listPayouts` / `listAdminUsers` endpoints unchanged).

## Files to change / delete
- `frontend/app/(admin)/admin/payouts/page.tsx` (tab shell)
- `frontend/app/(admin)/admin/payouts/_components/PayslipsPanel.tsx` (new, moved code)
- `frontend/app/(admin)/admin/coach-payslip/page.tsx` (→ redirect stub)
- `frontend/components/admin/screen-meta.ts`
- `frontend/e2e/specs/admin-shell.spec.ts`

## Verification
`pnpm typecheck && pnpm lint && pnpm e2e`. Manually: `/admin/coach-payslip` lands on Payslips tab; Payroll tab bulk actions and `payouts/[payoutId]` navigation unaffected. Backend untouched — audit-inventory manifest backend-side unaffected.

## Risks / rollback
- Low risk: payslip panel is read-only; payroll tab code untouched apart from wrapping. Rollback = git revert.
- Two different API generations coexist on one screen (`lib/api/admin` listPayouts vs `lib/api/v2/payroll`) — acceptable; note for future ledger-convergence work.

## PR checklist
- [x] Release note: "Coach payslips are now a tab on Payroll & payouts (old URL redirects)"
- [x] TRACKER.md: UIC4 → DONE + PR link
- [x] This plan: Status → DONE (PR #346, 2026-07-24)
