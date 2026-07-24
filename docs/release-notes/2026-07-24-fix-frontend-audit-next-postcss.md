# fix-frontend-audit-next-postcss

PR: #344

## What changed
The **Frontend Static** CI job runs `pnpm audit --audit-level=high` before its
Typecheck/Lint/Build steps. Four high-severity advisories made that scan exit 1,
so Typecheck, Lint, and Build never ran on any PR. This was pre-existing on
`main` and unrelated to any feature branch.

- Bumped `next` 15.5.18 → 15.5.21 — the minimum patch that clears the three
  high `next` advisories (GHSA-m99w-x7hq-7vfj DoS in App Router Server Actions,
  GHSA-89xv-2m56-2m9x SSRF in Server Actions on custom servers, and
  GHSA-p9j2-gv94-2wf4 SSRF in rewrites via attacker-controlled destination
  hostname).
- `next` pins `postcss@8.4.31` exactly, so the bump alone can't clear the
  postcss advisory (GHSA-6g55-p6wh-862q, arbitrary file read / info disclosure
  via attacker-controlled `sourceMappingURL` in CSS comments). Added a scoped
  `postcss@<8.5.12: '>=8.5.12'` override in `frontend/pnpm-workspace.yaml` so
  the vulnerable transitive copy floors to a patched release. postcss 8.5.x is
  API-compatible with 8.4.x, and the copies dedupe onto the direct
  `postcss@8.5.15` already present — net lockfile churn is a reduction.

`pnpm audit --audit-level=high` now exits 0. The remaining 3 low + 2 moderate
advisories (`uuid`, `protobufjs`, `@eslint/plugin-kit`, `body-parser`) are all
transitive, below the high gate, and have no non-major fix; they are left for a
separate dependency-hygiene pass. The CI step already ran at `--audit-level=high`,
so no threshold change was required.

## Deploy notes
none — no migrations, no env changes, no data backfill. Frontend dependency
bump only. `next` 15.5.18 → 15.5.21 is a same-minor patch; `@serwist/next`,
`@opennextjs/cloudflare`, and `@opennextjs/aws` all accept it (peer ranges
`next >=14` / `>=15.5.18 <16`), and `eslint-config-next` is unchanged.

## Risk / rollback
Low, despite Next.js bumps being high blast radius. Verified locally against the
full frontend suite: `pnpm audit --audit-level=high` (exit 0), `pnpm typecheck`,
`pnpm lint`, `pnpm build`, and both E2E suites — Chromium (108 passed) and
WebKit (108 passed). Backend is unaffected (full pre-push backend suite green).
Rollback is a pure revert of the three-file diff (`package.json`,
`pnpm-workspace.yaml`, `pnpm-lock.yaml`); nothing is written or migrated. The
postcss override should be removed once `next` itself pins `postcss >= 8.5.12`.
