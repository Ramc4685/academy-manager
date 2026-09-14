# batch-8-persona-hint-middleware

PR: #0

## What changed

- Fixes #451 (item a) — Persona shells (`/admin`, `/coach`, `/parent`, `/platform`) previously rendered on the client before any server-side check confirmed the visitor belonged to that persona, so a signed-in user could briefly paint the wrong shell (or one with no access) before the client-side / backend 404 kicked in. A new edge middleware (`frontend/middleware.ts`, matching those four route prefixes) now gates the request before the client shell paints. It reads a lightweight, non-HttpOnly `__cm_persona` hint cookie (`SameSite=Lax`, 30-day expiry) alongside the existing `__cm_identity` bridge cookie and decides: no session cookie at all → redirect to `/login?returnTo=<path+query>`; a hint that names other personas but not the requested one → redirect to that user's own home with `?access_denied=<persona>`; anything ambiguous (hint missing or unrecognized) → pass through unchanged, leaving the client and the backend's existing 404-on-wrong-persona check as the real gate.
- The decision logic lives in a pure, import-free module (`frontend/lib/auth/persona-route-guard.ts`) so it is unit-testable outside the edge runtime and can't drag Node-only code into the Workers/edge bundle.
- The hint cookie is written everywhere the persona is first known — post-login, both persona-auth hooks, and self-healing on every resolved `/me` — and is cleared everywhere `clearBffIdentityCookie()` already runs (login page, post-login bounce, `signOutCurrent`), so it can't outlive the session it describes.
- Admins/owners get `"coach"` included in the hint so existing coach-surface coverage (#632) keeps working; platform access adds `"platform"` to the hint.
- Login page: when the URL carries `returnTo` (meaning the edge gate bounced the request here) and Firebase still has a live session, the page hands the user straight to `/post-login` instead of re-prompting for a password. `/post-login` is outside the middleware matcher, so this cannot loop back into the gate.
- No build-tooling changes: `pnpm build` still runs `next build --webpack` (package.json untouched), the middleware exports no extra runtime config, and no route-manifest change was needed since the inventory scanners key off `frontend/app/**/page.tsx` entries only.

## Deploy notes

No migrations. No new required env vars. The `__cm_persona` cookie is a new non-HttpOnly cookie set by existing auth code paths (post-login, persona-auth hooks, `/me` resolution) — no backend schema or infra change. Ambiguous/missing-hint traffic passes through unchanged, so existing sessions without the cookie continue to work exactly as before (via the pre-existing client/backend gate) until they next go through one of the hint-writing paths.

## Risk / rollback

The middleware only ever redirects on two well-defined conditions (no session cookie; hint that names a different persona than the route requires) and passes through in every ambiguous case, so the existing client-side and backend 404 gating remains the fallback safety net if the hint is stale or wrong. The decision logic is isolated in a pure, unit-tested module separate from the edge runtime wiring. If anything regresses, revert this PR's merge commit.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
