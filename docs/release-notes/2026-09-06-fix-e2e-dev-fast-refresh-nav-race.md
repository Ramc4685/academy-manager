# fix-e2e-dev-fast-refresh-nav-race

PR: #PRNUM

## What changed
`next dev` now runs under Turbopack (`frontend/package.json`), which fixes a
deterministic WebKit e2e failure that had nothing to do with app code.

Under the webpack dev server, the first request for a not-yet-compiled route pushed an
HMR update to the page already open in the browser that React Refresh could not apply,
so `next dev` logged `[Fast Refresh] performing full reload` and did a full
`location.reload()` of the **current** URL roughly 1.5s into the request. That reload
cancelled the in-flight document load, and Playwright failed the step with
`Navigation to "<deep route>" is interrupted by another navigation to "<the route we came from>"`.
That is why the interrupting URL always looked like an "ancestor route" — it was simply
wherever the page happened to be, not a redirect. Instrumenting the page confirmed it:
no `router.replace`/`push`, no `window.location` assignment and no persona/role redirect
runs in the failing test; the only navigation is the dev server's own reload.

It hit `frontend/e2e/specs/admin-shell.spec.ts:725` (`owner / admin split › admin
without the owner scope …`) every run on `webkit-mobile`, because `/admin/reports` is
the heaviest route in the suite and its cold compile is slow enough for the reload
message to land mid-navigation; on a second run it moved to `/admin/reports/dues`, the
next uncompiled route. It is the same underlying cause as the "admin shell hard-navigates
seconds after paint" note on #650. Chromium passed only because it committed the
navigation before the reload arrived.

Turbopack applies those updates without a full reload. `playwright.config.ts` carries a
comment recording why the dev server must stay on it. The full `webkit-mobile` shard also
dropped from ~4m to 2.5m.

## Deploy notes
None — nothing ships. This changes the **dev** server only: `next build` and the
production runtime are untouched, and `next.config.ts` has no `webpack()` customisation
to port. Developers running `pnpm dev` get Turbopack too, which keeps the local
dev server and the Playwright `webServer` on the same builder (Playwright reuses an
already-running dev server locally, so a divergent script would silently reintroduce the
flake).

## Risk / rollback
Risk is confined to local development and the e2e gate. Verified by hand on this branch,
since the local pre-push gate skips WebKit:

- full `webkit-mobile` shard: 178 passed, 1 failed — the one failure is the separate
  `AdminReportsPage` crash on a partial payment feed that PR #667 fixes, which this race
  used to mask by aborting the test earlier.
- `admin-shell.spec.ts` on `webkit-mobile` with `--repeat-each=2`, with #667's app fix
  applied locally: 112/112 passed.
- full `chromium-mobile` + `chromium-desktop` shards: passed.

No spec was changed and no wait was added — the app behaviour under test was already
correct. Rollback is reverting the PR, which restores the webpack dev server and the
flake with it.
