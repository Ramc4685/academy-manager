# chore-next-postcss-security-bump

PR: #TBD

## What changed
Bumped `next` from `15.5.18` to `15.5.21` and added a tree-wide pnpm override
forcing `postcss` to `>=8.5.12`. Together these clear the four high-severity
advisories that had started failing the `pnpm audit --audit-level=high` step in
Frontend Static on every frontend PR:

- GHSA-m99w-x7hq-7vfj — Next.js DoS in App Router Server Actions
- GHSA-89xv-2m56-2m9x — Next.js SSRF in Server Actions on custom servers
- GHSA-p9j2-gv94-2wf4 — Next.js SSRF in rewrites via attacker-controlled host
- GHSA-6g55-p6wh-862q — PostCSS arbitrary file read via sourceMappingURL
  (transitive through Next's bundled postcss)

No application code changed. Remaining audit findings are moderate/low and
below the CI threshold.

## Deploy notes
None. Patch-level Next.js bump; no config or env changes. Standard frontend
deploy picks it up.

## Risk / rollback
Low. Patch release within the same Next.js 15.5 minor. If a regression appears,
revert this commit to restore `next@15.5.18` and drop the postcss override.
