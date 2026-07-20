# DS6 — Independent polish bundle (gating, nav, dead code, manifest)
Status: TODO
Size: M · Depends on: none hard; (c) should follow the UIC1-8 merges · Tracker: ../TRACKER.md

Bundle of five independent items. Each is its own checklist entry and its own small PR — do not combine into one mega-PR. Order among them is free except (c).

## Problem
Leftover polish items from the audit: client-only route gating (redirect flash + bundle leak), role-less `(shared)` layout, an admin nav at its scaling limit (24 items in 3 groups), a suspected-dead `lib/offline/*` tree, and PWA manifest colors that match nothing in the palette.

## Current behavior (verified 2026-07-20)

**(a) No middleware.** `frontend/middleware.ts` does not exist. Guards run client-side in `frontend/lib/auth/use-persona-auth.ts` after hydration; `:70-81` (`replaceLocation`) even papers over flaky `router.replace` with a 1s `window.location.replace` fallback timer. The identity token is already mirrored into a cookie: `frontend/lib/api/auth-bridge-cookie.ts` sets `__cm_identity` with `Path=/; SameSite=Strict; Max-Age=3600` (+`Secure` on https). GAPS.md #7 poses the decision: accept client-only OR add minimal middleware.

**(b) Role-less shared layout.** `frontend/app/(shared)/layout.tsx:13-21` checks only `onAuthChange` signed-in (`if (!user) router.replace("/login")`) — no role check for `/calendar` and `/messages`.

**(c) Admin nav at limit.** `frontend/components/admin/screen-meta.ts:43-93`: 24 items in WORK (10) / MONEY (9) / COMMS · OPS (5). Several rows are UIC merge targets (pause-requests → UIC2, coach-payslip → UIC4, session-economics + dues → UIC3, registrations/waitlist → UIC6, settings/self-service → UIC7, coaches+parents → UIC1).

**(d) `lib/offline/*` is NOT dead — audit claim does not verify.** `frontend/lib/offline/` contains `audit.ts`, `idb.ts`, `queue.ts`, `sync.ts`. Verification command and live result:
```
grep -rn "lib/offline" frontend/app frontend/components frontend/lib --include="*.ts*" | grep -v "^frontend/lib/offline"
→ app/(coach)/layout.tsx:10        import { startAutoSync } from "@/lib/offline/sync";
→ app/(coach)/coach/needs-review/page.tsx:5-6  imports from offline/audit + offline/queue
→ lib/query/persistence.ts:9       (doc comment reference)
```
The coach offline-writes feature actively uses it (`e2e/specs/coach-offline-writes.spec.ts` exists). **Do NOT delete.**

**(e) Manifest colors.** `frontend/public/manifest.webmanifest` sets `background_color` and `theme_color` both to `#0a0a0a` — a hex that appears nowhere in the Rally palette (`tailwind.config.ts:26-47`) or app chrome (`#0a0f1c` night, `#0f172a` ink, `#f8fafc` paper).

## Proposed change

### (a) Minimal middleware — RECOMMENDED over accepting client-only (S)
Recommendation: add middleware. Cost is ~30 lines; it kills the visible redirect flash, stops shipping protected-route JS to signed-out visitors, and lets the 1s `window.location.replace` hack in `use-persona-auth.ts:75-80` be deleted later. Spec:
- New `frontend/middleware.ts` with `config.matcher: ["/admin/:path*", "/coach/:path*", "/parent/:path*", "/calendar", "/messages"]` (persona route groups `(admin)`/`(coach)`/`(parent)`/`(shared)` — groups aren't in URLs, match the path prefixes).
- Logic: **cookie presence only** — if `request.cookies.get("__cm_identity")` is absent, redirect to `/login?next=<pathname>`. No verification, no role decode: the cookie is client-set and unsigned, backend remains the authorization authority (GAPS.md #7 notes this is UX/bundle hygiene, not an access-control fix). Document that explicitly in a file-top comment.
- Keep `usePersonaAuth` untouched in this PR (defense in depth + role routing stays client-side).
- E2E caveat: bypass-mode specs never set the cookie — either have middleware also allow when `NEXT_PUBLIC_E2E_AUTH_BYPASS=1` (build-time env, safe: never set in prod builds) or set the cookie in e2e setup. Prefer the env check; add one spec asserting signed-out `/admin` request → `/login` redirect (server-side, no flash).

### (b) Role check in shared layout (XS)
In `(shared)/layout.tsx`, after signed-in resolves, require at least one known persona role before rendering (reuse the role-resolution used by `use-persona-auth.ts` / persona layouts); unknown role → `router.replace("/login")`. Ten-minute change per GAPS.md #7.

### (c) Admin nav restructure — AFTER UIC merges (S)
Once UIC1/2/3/4/6/7 land, ~6 rows disappear. Target grouping (~15 items):
- **WORK**: Dashboard · Sessions · Students · Pathway · Admissions (UIC6) · Requests (incl. pauses, UIC2) · Directory (UIC1)
- **MONEY**: Payments · Billing Health · Billing Setup · Expenses · Payouts (incl. payslip, UIC4) · Reports (incl. economics + dues, UIC3)
- **OPS**: Messages · Waivers · Settings (incl. self-service, UIC7) · Audit logs
Pure `screen-meta.ts` edit + e2e testid updates (`admin-nav-*` slugs change for renamed rows). If UIC items stall, this item waits — do not restructure around pages that still exist.

### (d) lib/offline — re-scoped: keep, do not delete (XS)
Verification failed the audit's premise (imports exist, feature is live). Action: mark this sub-item **WONT-FIX (audit finding incorrect — lib/offline is imported by the coach surface)** in TRACKER notes. Optional 5-min follow-up: none needed; `coach-offline-writes.spec.ts` already guards it.

### (e) Manifest theme colors (XS)
Align to actual palette: `"background_color": "#f8fafc"` (rally-paper — app body background for coach/parent start URLs) and `"theme_color": "#0f172a"` (rally-ink — matches app chrome/status-bar intent). If DS1 has merged, cross-check the values against the final token set; also verify no `<meta name="theme-color">` in `app/layout.tsx` contradicts it (`grep -rn "theme-color\|themeColor" frontend/app/layout.tsx`).

## Files to change
- (a) `frontend/middleware.ts` (new), one new spec in `frontend/e2e/specs/`
- (b) `frontend/app/(shared)/layout.tsx`
- (c) `frontend/components/admin/screen-meta.ts` (+ e2e testid touch-ups)
- (d) none (tracker note only)
- (e) `frontend/public/manifest.webmanifest`

## Verification
- Per PR: `pnpm typecheck` · `pnpm lint` · `pnpm e2e`.
- (a): manual — signed-out hit on `/admin/students` returns a server redirect (curl -I shows 3xx to /login); signed-in flow unaffected; e2e suite green in bypass mode.
- (b): signed-in user with no persona role landing on `/calendar` is redirected; visual check no flash regression.
- (c): `admin-shell.spec.ts` green (update testids); visual check of sidebar + drawer grouping.
- (e): Lighthouse PWA audit / Chrome DevTools Application tab shows new colors; visual check of installed-app splash.

## Risks / rollback
- (a): matcher mistakes could block public routes — keep matcher to the four prefixes; middleware is a one-file revert. Cookie expiry (Max-Age 3600) vs Firebase session refresh: presence-check only, and the client bridge rewrites the cookie on token refresh, but test an idle-tab resume.
- (c): testid renames ripple into specs — grep `admin-nav-` across `frontend/e2e/` first.
- (e): none; cosmetic.

## PR checklist (per sub-item PR)
- [ ] Release note (a: "Server-side redirect for signed-out persona routes"; b: role gate; c: "Admin nav consolidated to ~15 items"; e: "PWA colors match brand")
- [ ] Update `docs/audit/TRACKER.md` DS6 row — track sub-items (a)-(e) in the PR/Issue column; mark (d) WONT-FIX with reason
- [ ] When (a),(b),(c),(e) are done and (d) is recorded: flip this plan's Status → DONE (PR #NNN, date)
