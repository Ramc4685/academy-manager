# fix-uim3-analytics-reports

PR: #362

## What changed
Adds three new read-only analytics sections to `/admin/reports`: enrollment
funnel, attendance trends, and coach utilization. These wire up three
backend endpoints in `backend/v2/interfaces/admin/reports_routes.py`
(`GET /admin/reports/enrollment-funnel`, `.../attendance-trends`,
`.../coach-utilization`) that had zero frontend callers since they shipped.
Attendance and coach utilization default to the trailing three months from
the page's existing month picker; the coach table resolves coach names via
the existing `queryKeys.admin.users("coach")` query, falling back to the
raw coach id if a name isn't available.

UIC3 (the tab consolidation of `/admin/reports`) has not merged yet — its
row in `docs/audit/TRACKER.md` is still `TODO` and the page has no tab bar.
Per UIM3's plan fallback ("if UIC3 slips, add sections to the current page
and let UIC3 absorb them"), these ship as three additional `Card` sections
rather than tabs; UIC3 can lift them into tabs later without any API or
data-layer changes.

New files: `frontend/components/admin/reports/{funnel-panel,
attendance-trends-panel,coach-utilization-panel}.tsx`. Also extends the
`/admin/reports` entry's `workflows`/`acceptance` lists in
`docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`, and
adds route stubs for the three new endpoints to
`frontend/e2e/specs/admin-shell.spec.ts` and
`frontend/e2e/specs/saas-launch-route-matrix.spec.ts` so the existing
`/admin/reports` mount coverage stays hermetic.

## Deploy notes
None. No new backend routes, migrations, or env vars — the three endpoints
already existed and were already deployed; this is a frontend-only change
that starts calling them.

## Risk / rollback
Low. All three sections are additive, client-side, read-only queries with
loading/empty/error states; no mutations, no changes to existing dashboard
widgets or exports on the page. If a response is malformed, panels degrade
to showing zero/empty rather than crashing (verified in review). Rollback
= revert this PR; the rest of `/admin/reports` is unaffected.
