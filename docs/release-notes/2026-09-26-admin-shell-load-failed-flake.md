# Nightly E2E WebKit: user-detail dirty-guard spec no longer aborts its own navigation

PR: #TBD

## What changed
- `e2e/specs/admin-shell.spec.ts` ("user detail warns before a link discards an unsaved profile edit") now waits for the `/admin/users` list to render after each link leave. Before, it waited only for the URL, then called `page.goto` straight away.
- Root cause: Next 16 updates the URL before the soft navigation's RSC payload (`/admin/users?_rsc=…`) and route chunks arrive. The immediate `page.goto` cancelled that fetch. WebKit rejects a cancelled fetch with `TypeError: Load failed`, the rejection reached the root error boundary (`app/global-error.tsx`), and its `console.error` logged it twice before the old document unloaded. The spec's console-error check then failed. Debug logging confirmed this: every cancelled RSC fetch and every error fell between the first leave and the second `page.goto`.
- Rate: about 1 in 30 serial runs, and 16 of 120 with 4 workers. After the fix: 200 of 200 on webkit-mobile with 4 workers, `--retries=0`.
- No stub was missing and the app logs nothing wrongly. A real user would only see this by reloading mid-navigation, while the page is unloading anyway. `BENIGN_PATTERNS` is unchanged and no assertion was weakened. The spec now also checks that the confirmed leave actually lands on the users list.

## Deploy notes
- Test-only change. No app code, migration, env var or backend change.

## Risk / rollback
- None for production. Rollback: revert this PR.
