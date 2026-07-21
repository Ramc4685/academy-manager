# fix-uic2-pause-requests-into-requests-tab

PR: #TBD

## What changed
Pause requests moved into **Requests → Pauses** tab. `/admin/requests`
gains a 5th tab (Makeups · Trials · Absences · Cancellations · **Pauses**)
with a `?tab=pauses` deep link; the old `/admin/pause-requests` route is
now a server redirect to `/admin/requests?tab=pauses` (bookmarks keep
working). The standalone "Pause requests" nav item and its topbar metadata
were removed from `components/admin/screen-meta.ts`. The pause table body
moved verbatim into `components/admin/requests/PausesTab.tsx`, keeping the
`["admin", "pause-requests"]` query key, the approve/decline mutations, and
the `data-testid="admin-pause-requests"` panel root so existing selectors
still resolve. Audit item UIC2.

## Deploy notes
none — frontend-only IA move. The `/api/v2/admin/pause-requests` API is
unchanged (no backend, migration, or env-var changes).

## Risk / rollback
Low: pure frontend move; mutations and endpoints untouched. e2e updated —
the route-matrix smoke rows point at `/admin/requests?tab=pauses`, and the
dedicated pause-detail test now asserts `/admin/pause-requests` redirects
there. Rollback = revert the single PR (old standalone page and nav item
restored).
