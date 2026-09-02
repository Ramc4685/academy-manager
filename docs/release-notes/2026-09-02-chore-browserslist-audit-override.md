# chore-browserslist-audit-override

PR: #621

## What changed
`frontend/pnpm-workspace.yaml` pins `browserslist: '>=4.28.7'`, and the
lockfile drops its `browserslist@4.28.6` entry as a result.

Two advisories against `browserslist <=4.28.6` were published after
main's last green run on 2026-09-01: GHSA-c83g-rgw3-j3cx (unbounded
memory growth — no cache eviction on distinct query results, eventual
OOM) and GHSA-73wf-gq98-2v4g (uncaught crash and prototype write via an
untrusted `browserslist-stats.json` in `normalizeStats`). Both are fixed
in 4.28.7.

The `Dependency vulnerability scan` step of the `Frontend Static` job
runs `pnpm audit --audit-level=high`, which queries the live advisory
registry rather than anything in the repository. An unchanged lockfile
therefore flipped from pass to fail with no commit involved, and CI Gate
went red on every open PR at once, not just the one that happened to
surface it.

`@serwist/next` was the only remaining chain resolving 4.28.6; every
other consumer had already resolved 4.28.7. The pin consequently removes
a lockfile entry rather than adding one, which is why the lockfile diff
is a net deletion.

No `auditConfig.ignoreGhsas` entry accompanies this pin. The neighbouring
`undici`, `nanoid` and `js-yaml` pins need one because `pnpm audit`
evaluates the upstream declared range even when the lockfile applies the
patched override; here the audit accepts the overridden range, so an
ignore would only suppress a future signal for no benefit.

## Deploy notes
No migration, no schema change, no environment variable, no manual step.

`browserslist` is a build-time dependency: it resolves compilation
targets for the bundler and PostCSS and ships no code to the client. The
deployed bundle is unchanged in behaviour; only the target-resolution
library used to produce it moves by one patch release.

Anyone with an existing checkout should run `pnpm install` after pulling,
since `pnpm install --frozen-lockfile` in CI now expects the updated
lockfile.

## Risk / rollback
Low. The change is confined to a patch bump within `4.28.x` of a
build-time package, verified locally by running every step of the
`Frontend Static` job in a clean worktree off main: `pnpm install
--frozen-lockfile`, `pnpm audit --audit-level=high`, `pnpm typecheck`,
`pnpm lint` and `pnpm build` all exit 0. The audit went from
`3 high (1 ignored)` and exit 1 to `1 high (1 ignored)` and exit 0; the
remaining high is the pre-existing, already-ignored `extract-zip`
advisory (GHSA-jmr9-qjv8-65gv), which still has no patched release on
the registry.

Reverting the merge restores the previous resolution and needs no
cleanup — but it also restores the red CI Gate, since the advisories are
a property of the registry rather than of this repository. Anything that
reverts this pin has to address them another way.
