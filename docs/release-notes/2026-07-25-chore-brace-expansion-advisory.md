# chore-brace-expansion-advisory

PR: #351

## What changed
Clears the newly-published high-severity `brace-expansion` advisory
[GHSA-mh99-v99m-4gvg](https://github.com/advisories/GHSA-mh99-v99m-4gvg)
(unbounded brace expansion → out-of-memory process crash), which started
failing `pnpm audit --audit-level=high` in Frontend Static on every open PR
(#348, #349, #350). Dependency-only; no application code.

- `frontend/pnpm-workspace.yaml`: the `brace-expansion@5` override moves from
  `^5.0.7` to `^5.0.8`. `5.0.8` is the only patched release upstream shipped,
  so this is the real fix for that copy.
- `frontend/pnpm-workspace.yaml`: adds an `auditConfig.ignoreGhsas` entry for
  this one GHSA, covering the two copies that **cannot** be fixed (see below).
- `frontend/pnpm-lock.yaml`: regenerated for the bumped range.

Also de-flakes `e2e/specs/admin-session-creation-ui.spec.ts`, which failed this
PR's WebKit run. `playwright.config.ts` sets `failOnFlakyTests` under CI, so a
single flaky retry fails the job — and this race sits in a spec every frontend
PR runs, so it was blocking the same set of PRs as the advisory above. The coach
field renders a placeholder `<input>` ("Loading coaches...") until the
`admin/users` query resolves and only then swaps to a `<select>`; both
`selectOption()` call sites now wait for the target `<option>` to be attached
first, which cannot be satisfied by the placeholder input. Fixed at the create
dialog (`Coach`) as well as the replacement dialog (`Replacement coach`) — the
create-dialog call had the identical latent race and merely happened to win.

### Why the 1.x/2.x copies are suppressed rather than bumped
Three copies of `brace-expansion` resolve in this tree: `5.0.7` (fixed above),
`1.1.16`, and `2.1.2`. Upstream published **no** patched 1.x or 2.x release —
`>=5.0.8` is the sole fixed version — and those two cannot be overridden to v5:
v5's CommonJS entry exports an object (`{ expand, EXPANSION_MAX, ... }`)
instead of the callable `module.exports` that its only consumers here,
`minimatch@3.1.5` and `minimatch@5.1.9`, invoke as
`require("brace-expansion")(...)`. Forcing v5 there swaps a theoretical DoS for
a certain `TypeError` at build time, so it is a runtime break, not a fix.

Both residual paths are build-time only, reached exclusively through
`@serwist/next`'s bundled `glob@7`/`glob@9` (the Next PWA service-worker build
plugin): `. > @serwist/next > [@serwist/build >] glob > minimatch >
brace-expansion`. Nothing in that chain is shipped to the browser or evaluated
in the request path, and the only glob patterns it expands are this repo's own
build globs — never attacker-controlled input. The suppression is scoped to
this single GHSA (not a severity-threshold change), and the rationale plus the
re-evaluation trigger are recorded inline in `pnpm-workspace.yaml`: revisit
when `@serwist/next` moves off `glob@7`/`@9`, which pulls `minimatch@10` and
with it `brace-expansion@5`.

## Deploy notes
none — dependency-resolution change only. No API, schema, env-var, or runtime
code changes, and no shipped bundle contents change (`brace-expansion` is
build tooling in every path here).

## Risk / rollback
Low. Verified locally on this branch: `pnpm audit --audit-level=high` exits 0
(`3 low | 2 moderate | 1 high (1 ignored)`), `pnpm install --frozen-lockfile`
resolves cleanly, `pnpm typecheck` passes, and `pnpm build` completes with the
full static route map generated — which exercises the `@serwist/next` plugin
whose `glob`/`minimatch` chain owns the suppressed paths, confirming the
`brace-expansion@5` bump did not break service-worker generation. The
suppression is one GHSA id in one file; rollback = revert this PR, which
restores `^5.0.7` and removes the `auditConfig` block (and re-fails the audit
gate).
