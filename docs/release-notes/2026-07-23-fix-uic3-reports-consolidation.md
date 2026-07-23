# fix-uic3-reports-consolidation

PR: #TBD

## What changed
Session economics and Dues follow-up now live under **Reports** (old URLs
redirect). Following the existing hub-and-spoke pattern already used by the
reports sub-pages (`refunds`, `revenue-by-category`, `deposit-slip`), the two
standalone pages moved to `/admin/reports/session-economics` and
`/admin/reports/dues` and are now listed as cards under "Financial reports"
on the hub. The old `/admin/session-economics` and `/admin/dues` routes are
now server redirects to the new paths (bookmarks keep working). The two
standalone nav items were removed from `components/admin/screen-meta.ts`
(MONEY group shrinks 9 → 7); their `SCREEN_META` breadcrumbs moved to the
new keys. Page content, testids (`admin-session-economics`, `admin-dues`),
query keys, and the dues page's `useAdminAction` topbar "send reminders"
button are unchanged — only the route moved. Audit item UIC3.

## Deploy notes
none — frontend-only IA move. Backend `dues-followup` and
`reports/session-economics` APIs are unchanged.

## Risk / rollback
Low: pure frontend move; mutations and endpoints untouched. e2e updated —
route-mount smoke rows in `admin-shell.spec.ts` and
`saas-launch-route-matrix.spec.ts` point at the new `/admin/reports/*`
paths, with a network stub added for `session-economics` (previously
exercised only via the standalone route). Rollback = revert the single PR
(old standalone pages and nav items restored).
