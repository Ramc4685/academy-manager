# UIC2 — Pause requests → 5th tab of /admin/requests
Status: DONE (PR #TBD, 2026-07-21)
Size: S · Depends on: none · Tracker: ../TRACKER.md

## Problem
`/admin/pause-requests` (196L) is a standalone nav item for a single approve/decline table, while `/admin/requests` (729L) is already the 4-tab approval queue for the identical pattern. One more nav item than needed; parents' pause requests live apart from their other requests.

## Current behavior (verified)
- `app/(admin)/admin/requests/page.tsx`: `type RequestTab = "makeups" | "trials" | "absences" | "cancellations"` (line 28), `TABS` array (30-35), `role="tablist"` pill bar (69-87), conditional panels `{tab === "makeups" && <MakeupsTab />}` etc. (89-92). Each tab is a self-contained function component using TanStack Query + `lib/api/admin` calls.
- `app/(admin)/admin/pause-requests/page.tsx`: query key `["admin", "pause-requests"]`, `listAdminPauseRequests` / `approvePauseRequest` / `declinePauseRequest` from `lib/api/admin`, one table (`data-testid="admin-pause-requests"`), `mapStatus` chip helper, Skeleton.
- Nav: `screen-meta.ts:55` (Pause requests item), `:56` (Requests item). Meta: `:117-118`.
- e2e: `admin-shell.spec.ts:80` and `saas-launch-route-matrix.spec.ts:97-101` visit `/admin/pause-requests` expecting `data-testid="admin-pause-requests"`; both stub `**/api/v2/admin/pause-requests*` (`admin-shell.spec.ts:220`, route-matrix `:139`).

## Proposed change (target IA)
`/admin/requests` gains a 5th tab. Tab names: **Makeups · Trials · Absences · Cancellations · Pauses**. Support `?tab=pauses` deep link. `/admin/pause-requests` redirects to `/admin/requests?tab=pauses`. Nav item removed.

## Implementation steps
1. In `requests/page.tsx`: extend `RequestTab` with `"pauses"`, append `{ id: "pauses", label: "Pauses" }` to `TABS`, add `{tab === "pauses" && <PausesTab />}`. Initialize `tab` from `useSearchParams().get("tab")` (validate against TABS) so the redirect deep-links; optionally write back on click like `settings/page.tsx` does with `?panel=`.
2. Move the pause-requests page body into a `PausesTab` component (either inline in `requests/page.tsx` matching the other four tabs, or `components/admin/requests/PausesTab.tsx` given the page is already 729L — prefer the separate file). Keep the query key `["admin", "pause-requests"]`, mutations, and `data-testid="admin-pause-requests"` on the tab panel root so existing selectors keep working. Replace the `any`-typed `mapStatus` with `ChipVariant` while moving.
3. Replace `app/(admin)/admin/pause-requests/page.tsx` with a redirect stub: `redirect("/admin/requests?tab=pauses")` (bookmarks keep working).
4. `screen-meta.ts`: delete nav item `:55`; delete `SCREEN_META["/admin/pause-requests"]` (`:117`); update the Requests subtitle (`:118`) to "Makeups, trials, absences, cancellations, pauses".
5. e2e: update `admin-shell.spec.ts` and `saas-launch-route-matrix.spec.ts` entries for `/admin/pause-requests` to either (a) assert redirect to `/admin/requests?tab=pauses` and that `admin-pause-requests` testid is visible there, or (b) point the row at the new URL. Keep the `**/api/v2/admin/pause-requests*` network stubs — the API route is unchanged.

## Files to change / delete
- `frontend/app/(admin)/admin/requests/page.tsx` (5th tab + `?tab=` init)
- `frontend/components/admin/requests/PausesTab.tsx` (new, moved code)
- `frontend/app/(admin)/admin/pause-requests/page.tsx` (→ redirect stub)
- `frontend/components/admin/screen-meta.ts`
- `frontend/e2e/specs/admin-shell.spec.ts`, `frontend/e2e/specs/saas-launch-route-matrix.spec.ts`

## Verification
`pnpm typecheck && pnpm lint && pnpm e2e`. Manually: `/admin/pause-requests` lands on Pauses tab; approve/decline still invalidates and refreshes. Backend untouched (`/api/v2/admin/pause-requests` API unchanged) — audit-inventory manifest/backend side unaffected.

## Risks / rollback
- Low: pure frontend move; mutations/endpoints unchanged. Rollback = git revert (old page restored, nav item back).
- Watch: `?tab=` param must not fight the existing `useState` default ("makeups") — read param once on mount.

## PR checklist
- [ ] Release note: "Pause requests moved into Requests → Pauses tab (old URL redirects)"
- [ ] TRACKER.md: UIC2 → DONE + PR link
- [ ] This plan: Status → DONE (PR #NNN, date)
