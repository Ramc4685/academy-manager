# chore-ci-audit-ignore-extract-zip

PR: (pending)

## What changed
Unblocked the CI **Frontend Static** job, which has failed on every PR since
~2026-08-16.

The job runs `pnpm audit --audit-level=high` (`.github/workflows/production.yml`)
before typecheck, lint, and build. It was exiting 1 on GHSA-jmr9-qjv8-65gv
(`extract-zip <=2.0.1`, unvalidated symlink path traversal), so the whole
frontend gate aborted before producing any real signal.

- Added `GHSA-jmr9-qjv8-65gv` to `auditConfig.ignoreGhsas` in
  `frontend/pnpm-workspace.yaml`, alongside the seven advisories already
  suppressed there. Every other entry is paired with a patched `overrides` pin;
  this one is the documented exception, so it carries a comment explaining why
  there is nothing to pin to.
- Documented the audit gate and the suppression in `frontend/README.md`,
  including the removal condition.

Why the advisory cannot be fixed by upgrading:

- It is **dev-only and transitive** — `@lhci/cli` → lighthouse → puppeteer-core
  → `@puppeteer/browsers` → `extract-zip`, and `size-limit` →
  `@size-limit/preset-app` → estimo → find-chrome-bin → `@puppeteer/browsers`.
  It never reaches the deployed bundle (`pnpm audit --audit-level=high --prod`
  already exits 0).
- **No patched version exists.** The advisory names `>=2.0.2` as patched, but
  `extract-zip@2.0.1` is still the latest release on the registry, so there is
  no version to upgrade or override to.

The audit level stays at `high` and the step is still enforced — only this one
advisory is suppressed. Note the config lives in `pnpm-workspace.yaml`, not
`package.json`: pnpm 11 no longer reads a `pnpm` field in `package.json` and
warns that `pnpm.auditConfig` was ignored.

## Deploy notes
none — CI/tooling configuration only. No production code, migrations, env vars,
or runtime dependencies changed; `frontend/package.json` and
`frontend/pnpm-lock.yaml` are untouched.

## Risk / rollback
Low. The risk is that a future advisory affecting `extract-zip` under the same
GHSA id would also be silenced — bounded, because the package is dev-only and
never shipped, and the entry has a stated removal condition (upstream publishes
a fix, or the puppeteer chain drops `extract-zip`). All other advisories at
`high` and above still fail the build. Rollback is deleting the single
`ignoreGhsas` line, which restores the current red gate.
