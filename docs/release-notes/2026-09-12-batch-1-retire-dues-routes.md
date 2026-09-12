# Retire Dues Routes

PR: #0

## What changed

- Fixes #689 — `/admin/dues` and `/admin/reports/dues` now redirect via `next.config.ts` (`redirects()`) instead of via a server-component RSC page inside the `(admin)` route group. Config redirects are matched before route resolution, so these two retired paths no longer render the full `(admin)` layout (session resolution + shell BFF calls) just to throw a redirect signal. That authenticated render was blowing the Cloudflare Workers per-request resource ceiling and serving `Error 1102` to anyone who still hit the old bookmarked URLs, instead of ever forwarding them to `/admin/payments`.

## Deploy notes

- No migrations. No environment variable changes. No manual steps — this is a pure frontend routing change (`frontend/next.config.ts`), and the redirect takes effect as soon as the new build is live.

## Risk / rollback

- Low risk: the change only affects two already-retired paths (`/admin/dues`, `/admin/reports/dues`), which previously either redirected (successfully) or errored (Error 1102) — there is no new destination behavior, only a cheaper way of reaching the same `/admin/payments` destination.
- Rollback: revert this PR (or the merge commit) to restore the RSC-page redirect; no data or state changes are involved.
