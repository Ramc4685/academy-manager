# UIC8 — Delete/redirect the shared Calendar and Messages stubs
Status: DONE (PR #TBD, 2026-07-23)
Size: XS · Depends on: UIM13 decision (see below) · Tracker: ../TRACKER.md

## Problem
`app/(shared)/calendar/page.tsx` (38L) and `app/(shared)/messages/page.tsx` (41L) are shell pages whose entire function is: fetch `getCurrentUser`, then render a paragraph + one link to the real persona screen. Dead weight and a confusing intermediate hop for anyone who lands there.

## Current behavior (verified)
- Calendar stub: role-switched link — admin → `/admin/sessions`, coach → `/coach/sessions`, parent → `/parent/dashboard`, else `/login`. Uses ad-hoc query key `["me","calendar"]`.
- Messages stub: admin → `/admin/messages`, non-admin → `/post-login`. Ad-hoc key `["me","messages"]`.
- **Inbound links: none.** Grep across `app/`, `components/`, `lib/`, `middleware.ts`, `app/post-login` for `"/calendar"` / `"/messages"` hrefs (excluding persona-prefixed paths) returns nothing; the only hit is the messages stub itself. e2e: only `e2e/fixtures/saas-stubs.ts` mentions "shared" (network stubs, not these routes). They are reachable only by typed URL / stale bookmark.
- UIM13 (real shared Messages inbox + Calendar, TRACKER "UI — Missing features") is planned but sized L with new backend needed — not imminent.

## Proposed change (target IA)
Per the audit note: since UIM13 is planned but not imminent, **replace both stubs with redirect pages now** (preserving the role dispatch), real screens later at the same URLs. This keeps `/calendar` and `/messages` as stable persona-agnostic entry points (useful for future notification emails) at ~15 lines each with zero UI to maintain.
- `/calendar` → server-side role lookup → `redirect()` to `/admin/sessions` | `/coach/sessions` | `/parent/dashboard` | `/login`.
- `/messages` → `/admin/messages` | `/post-login`.
If UIM13 gets scheduled within the same milestone, skip this item (WONT-FIX) and let UIM13 replace the stubs directly.

## Implementation steps
1. Check how `(shared)/layout.tsx` resolves the user: if role is available server-side, implement the two pages as server components calling `redirect()`. If role is client-only (Firebase token), keep them as minimal client components that `router.replace(...)` on load instead of rendering the link card — same effect, no interstitial UI.
2. Rewrite `app/(shared)/calendar/page.tsx`: preserve the exact role→destination mapping above; drop the card/copy markup and the ad-hoc `["me","calendar"]` query key (reuse the shared `me` query key from `lib/query/keys.ts` if a client component is needed).
3. Same for `app/(shared)/messages/page.tsx` with its admin/non-admin mapping.
4. No `screen-meta.ts` change (these are outside the admin shell; never in nav). No redirects config needed — the routes themselves remain.
5. e2e: no spec visits these routes today; optionally add a 2-line smoke asserting `/calendar` as admin lands on `/admin/sessions`.

## Files to change / delete
- `frontend/app/(shared)/calendar/page.tsx` (→ redirect page)
- `frontend/app/(shared)/messages/page.tsx` (→ redirect page)
- (nothing else — verified no inbound links)

## Verification
`pnpm typecheck && pnpm lint && pnpm e2e`. Manually per persona: `/calendar` and `/messages` land on the correct workspace with no flash of interstitial content; unauthenticated visit ends at `/login`/`/post-login`. Backend untouched — audit-inventory manifest backend-side unaffected.

## Risks / rollback
- Near-zero: no inbound links exist, so only bookmarks are affected — and they now skip a click. Rollback = git revert.
- Coordinate with UIM13: when real screens ship, they replace these redirect pages at the same paths (note this in UIM13's plan).

## PR checklist
- [x] Release note: "/calendar and /messages now jump straight to your workspace"
- [x] TRACKER.md: UIC8 → DONE + PR link (or WONT-FIX if UIM13 supersedes)
- [x] This plan: Status → DONE (PR #NNN, date)
