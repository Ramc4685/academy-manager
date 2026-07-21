# fix-deps-pin-patched-js-yaml-brace-expansion

PR: #318

## What changed
`pnpm audit --audit-level=high` (the "Frontend Static" CI job's "Dependency
vulnerability scan" step) started failing on every branch after two new
high-severity advisories were published: GHSA-52cp-r559-cp3m (js-yaml
YAML merge-key chains force quadratic CPU consumption) and
GHSA-3jxr-9vmj-r5cp (brace-expansion exponential-time expansion DoS). All 13
findings (3 low, 5 moderate, 5 high) live in dev-tool transitive
dependencies only — `eslint>@eslint/eslintrc>js-yaml`,
`@lhci/cli>@lhci/utils>js-yaml`, and several `glob>minimatch>brace-expansion`
chains under `@serwist` — nothing reachable from runtime/production code.

Forces patched versions via `frontend/pnpm-workspace.yaml` `overrides`, the
same pattern already used for the esbuild/tmp/undici pins (QW1, PR #310):
`js-yaml` → `>=3.15.0` / `>=4.3.0`, `brace-expansion` → `>=1.1.16` /
`>=2.1.2` / `>=5.0.7`.

## Deploy notes
None. Dev-dependency version pins only — no runtime code, migration, or
environment variable change.

## Risk / rollback
Very low risk — this only tightens transitive dev-tool dependency versions
already compatible with the packages that depend on them (verified via
`pnpm typecheck` and `pnpm lint`, both clean). Revert the merge commit to
drop the overrides; `pnpm audit --audit-level=high` will start failing again
until the advisories are otherwise addressed.
