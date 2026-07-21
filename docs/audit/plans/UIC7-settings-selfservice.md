# UIC7 — Self-service policy → panel of /admin/settings
Status: DONE (2026-07-21)
Size: XS · Depends on: none · Tracker: ../TRACKER.md

## Problem
`/admin/settings/self-service` (216L) has its own top-level nav item ("Self-service", `screen-meta.ts:89`) even though it is a settings child, while `/admin/settings` (65L) is already a clean `?panel=` tab shell with 7 panels.

## Current behavior (verified)
- `app/(admin)/admin/settings/page.tsx`: `SettingsTabs` + `?panel=` query param routing (`coercePanel`, `history.replaceState`, lines 20-51) over panels `academy | fees | gateway | notify | roles | branding | data`, each a component in `components/admin/settings/*-panel.tsx` (`SETTINGS_TABS` in `components/admin/settings/settings-tabs.tsx`).
- `app/(admin)/admin/settings/self-service/page.tsx`: form over `getSelfServicePolicy`/`updateSelfServicePolicy` (`queryKeys.admin.selfServicePolicy()`), dirty-tracking, cents/dollars conversion.
- Nav: `screen-meta.ts:88` (Settings), `:89` (Self-service — separate item, same `cog` icon). Meta `:133-134`. Note the Settings item's `match: startsWith("/admin/settings")` already highlights both — the two nav items double-highlight today.
- e2e: `parent-self-service.spec.ts` and `local-auth-qa.spec.ts` reference self-service (admin policy side may be visited to set up parent flows — check before changing URLs).

## Proposed change (target IA)
Self-service becomes an 8th settings panel: `/admin/settings?panel=self-service`, tab label "Self-service". The route `/admin/settings/self-service` redirects there. Nav item at `screen-meta.ts:89` removed (net −1 nav item).

## Implementation steps
1. Extract the page body into `components/admin/settings/self-service-panel.tsx` (move code as-is; keep query keys and the form's testids/`role="alert"` markup).
2. Add `{ key: "self-service", label: "Self-service" }` to `SETTINGS_TABS` in `components/admin/settings/settings-tabs.tsx`; add `{active === "self-service" && <SelfServicePanel />}` in `settings/page.tsx` (`coercePanel` picks it up automatically via `SETTINGS_TABS`).
3. Replace `app/(admin)/admin/settings/self-service/page.tsx` with `redirect("/admin/settings?panel=self-service")` (bookmarks keep working).
4. `screen-meta.ts`: delete nav item `:89`; delete `SCREEN_META["/admin/settings/self-service"]` (`:134`) — the redirect fires before the shell needs it. This also fixes the current double-highlight.
5. e2e: grep `parent-self-service.spec.ts` / `local-auth-qa.spec.ts` for `/admin/settings/self-service` visits; point them at `?panel=self-service` or rely on the redirect.

## Files to change / delete
- `frontend/components/admin/settings/self-service-panel.tsx` (new, moved code)
- `frontend/components/admin/settings/settings-tabs.tsx` (+1 tab)
- `frontend/app/(admin)/admin/settings/page.tsx` (+1 panel branch)
- `frontend/app/(admin)/admin/settings/self-service/page.tsx` (→ redirect stub)
- `frontend/components/admin/screen-meta.ts`
- `frontend/e2e/specs/parent-self-service.spec.ts`, `frontend/e2e/specs/local-auth-qa.spec.ts` (if they visit the old URL)

## Verification
`pnpm typecheck && pnpm lint && pnpm e2e`. Manually: policy form loads, dirty-save works, old URL redirects into the panel. Backend untouched (`self-service-policy` API unchanged) — audit-inventory manifest backend-side unaffected.

## Risks / rollback
- Minimal — the settings shell was built for exactly this. Rollback = git revert.

## PR checklist
- [ ] Release note: "Self-service policy moved into Settings (old URL redirects)"
- [ ] TRACKER.md: UIC7 → DONE + PR link
- [ ] This plan: Status → DONE (PR #NNN, date)
