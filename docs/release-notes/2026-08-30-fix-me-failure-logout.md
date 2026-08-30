# me-failure-logout

PR: #580

## What changed
The persona-auth guards (`usePersonaAuth` / `usePlatformAuth`) and the
post-login page treated every `getCurrentUser()` rejection as an auth
failure. `/me` is fetched as a raw promise (`dedup:false`, outside
react-query), so no retry policy applied: one backend 500 during a deploy, a
network blip, or the client's own 20-second abort cleared the identity
cookie and hard-redirected an authenticated user to /login across every
persona shell, even though the Firebase session was still valid.

The guards now classify failures. HTTP 401/403 remain real auth failures and
still redirect to /login carrying the backend reason code. Everything else
(5xx, network error, timeout/abort) is retried up to 3 times with 500ms/1.5s
backoff via the new `withTransientRetry` helper in
`frontend/lib/auth/me-failure.ts`; if it still fails, the hooks surface an
`unavailable` state and all five persona/platform layouts render a shared
"We can't reach the server right now" screen with a Retry button instead of
bouncing to /login. The post-login page does the same and only clears the
BFF identity cookie on a genuine 401/403.

## Deploy notes
Frontend-only; no migration, no API change, no new route. The `/me` call may
now be issued up to 3 times per guard evaluation during a backend outage —
negligible load, and only while /me is failing.

## Risk / rollback
Worst case, a genuinely dead session whose /me rejection somehow arrives
without a 401/403 status would show the retry screen instead of the login
page — the user resolves it by pressing Retry (which then yields the 401 and
redirects) or logging out manually; no protected data renders in that state,
since the shell never mounts children until /me succeeds. Roll back by
reverting the merge commit; no persisted state is involved.
