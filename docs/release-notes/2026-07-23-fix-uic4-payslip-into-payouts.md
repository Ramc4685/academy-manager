# fix-uic4-payslip-into-payouts

PR: #346

## What changed
Coach payslips moved into a **Payslips** tab on `/admin/payouts`. The page
gains a two-tab header (Payroll · Payslips, pill tablist matching the
`admin/requests` pattern) with a `?tab=payslips` deep link; the old
`/admin/coach-payslip` route is now a server redirect to
`/admin/payouts?tab=payslips` (bookmarks keep working). The standalone
"Coach payslip" nav item and its topbar metadata were removed from
`components/admin/screen-meta.ts`, and the Payouts entry was retitled
"Payroll & payouts". The payslip card grid moved verbatim into
`app/(admin)/admin/payouts/_components/PayslipsPanel.tsx`, keeping the
`["admin", "users", "coach"]` / `["admin", "finance", "payouts",
"coach-payslip"]` query keys and the `data-testid="admin-coach-payslip"`
panel root so existing selectors still resolve; its loading/empty states
now use the DS3 `Skeleton`/`EmptyState` primitives instead of bespoke
markup. Audit item UIC4.

Also widened the tree-wide `postcss` pnpm override from `>=8.5.12` to
`>=8.5.18` (`frontend/pnpm-workspace.yaml`) to clear a newly-published
high-severity advisory (GHSA-r28c-9q8g-f849, path traversal via
sourceMappingURL auto-loading) that started failing `pnpm audit
--audit-level=high` in Frontend Static on this PR; unrelated to the
payslip/payouts move, just needed to get CI green.

## Deploy notes
none — frontend-only IA move. `listAdminUsers`/`listPayouts` (`lib/api/admin`)
are unchanged (no backend, migration, or env-var changes).

## Risk / rollback
Low: pure frontend move; the payroll tab's bulk generate/recompute/export
mutations and `payouts/[payoutId]` navigation are untouched. e2e updated —
a dedicated test asserts `/admin/coach-payslip` redirects to
`/admin/payouts?tab=payslips` and that both the `admin-payouts` and
`admin-coach-payslip` testids render there. Rollback = revert the single PR
(old standalone page and nav item restored).
