# frontend-audit-advisories

PR: #1063

## What changed
Clears newly published frontend dependency advisories that failed the `pnpm audit --audit-level=high` gate on `main` and blocked the production deploy of #1062: `sharp` 0.35.4 -> 0.35.5 and `source-map-js` 1.2.1 -> 1.2.2 (both transitive via next), plus dev-only `proxy-addr` 2.0.8 and `compression` 1.8.2 (via @lhci/cli). `braces` GHSA-vfj7-8cjw-p6xm is ignored with a comment: it has no patched release and is reached only through eslint-config-next. No app code changes.

## Deploy notes
None.

## Risk / rollback
`sharp` is used by next for image optimization; 0.35.5 is a patch release. If image handling misbehaves, revert the PR.
