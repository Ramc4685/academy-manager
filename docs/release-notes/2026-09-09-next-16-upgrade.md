# next-16-upgrade

PR: #TBD

## What changed
The frontend moves to Next 16 (`next@16.3.4`, `eslint-config-next@16.3.4`). The
production build is pinned to webpack via `"build": "next build --webpack"`. Next 16
defaults to Turbopack for both `next dev` and `next build`, and `@serwist/next` does not
support Turbopack — its own source warns so, tracked upstream at serwist/serwist#54.
Without `--webpack` the build hard-errors; adding a `turbopack: {}` block to
`next.config.ts` makes the error go away but silently ships **no service worker**, so
that option was considered and deliberately rejected. `next.config.ts` is unchanged.

`"dev"` keeps `--turbopack`: Serwist is disabled in development, so nothing is lost
there and local startup stays fast.

`frontend/tsconfig.json` changes `"jsx": "preserve"` to `"jsx": "react-jsx"`. Next 16's
`next typegen` applies this automatically and it is a legitimate part of the migration.
It landed inside the e2e-stub commit rather than the upgrade commit, so it is called out
here rather than being inferable from the commit split.

`.open-next/**` is added to the eslint ignore list. It is gitignored build output that
was never in eslint's own ignores, so `pnpm lint` reported 15 errors from generated
bundles after a local Cloudflare build.

Four e2e fixture gaps are fixed: `/parent/profile`, `/parent/academy`,
`/coach/sessions/*/announcements` and `/admin/payments/collections`. All four are real
latent holes rather than Next 16 instability. A page the spec lands on fetches the
endpoint, no route handled it, the request fell through to the dev server with no backend
behind it, returned 500, and tripped the trailing clean-console assertion. Next 15
happened to mask them. Each endpoint was read out of the failing test's trace rather than
guessed at, and `/parent/academy` gets a shared helper because five parent pages read it.

One of these is worth remembering: `**/api/v2/admin/payments*` does not match
`/payments/collections`, because Playwright stops a `*` wildcard at the path separator.
A glob that looks like it covers a whole endpoint family may quietly cover only part of
it.

## Deploy notes
None. No migration, no new env vars, no new endpoint, no infrastructure change.

The deploy path was verified end to end rather than assumed. Production ships via
`pnpm deploy:cloudflare` -> `opennextjs-cloudflare build`, which invokes the package's
own `build` script and therefore inherits `--webpack`. A local run exits 0 and emits a
57104-byte `public/sw.js`, so the service worker still ships. Re-verify this only if the
build wiring changes.

## Risk / rollback
The `--webpack` flag is load-bearing and is the main thing to preserve. Anyone removing
it, or "fixing" a Turbopack build error by adding `turbopack: {}`, will ship a build with
no service worker and no error to show for it. That is the one regression this change can
produce and it is invisible at build time, so it is worth a second look in review of any
future build-script edit.

Serwist configurator mode (`@serwist/cli`, which is Turbopack-native) is the longer-term
fix that would let both dev and build run on Turbopack. It is deliberately not attempted
here: it changes how the service worker is generated and deserves its own change with its
own verification. Rollback is reverting the PR, which restores `next@15.5.24`.
