# fix-ds4-parent-migration

PR: #TBD

## What changed
Migrated parent-surface pages off ad-hoc inline `style={{...}}`/raw-hex
styling and onto the Rally design system (tokens from DS1, de-hexed
primitives from DS2, `FormField`/`Skeleton`/`EmptyState`/`Modal`/`Toast`
from DS3). Pure styling convergence — no copy changes, no layout redesign,
no data-flow changes; every `data-testid`/`role` used by e2e is preserved.
Audit item DS4.

Pages migrated this PR (see the Status line in
`docs/audit/plans/DS4-parent-migration.md` and the DS4 row in
`docs/audit/TRACKER.md` for exactly which ones landed):

- `app/(parent)/parent/waivers/page.tsx` — status pills converted to
  `Chip`, panels to `Card`, submit button to `Button`, mutation success
  routed through `Toast` (`useToast`) instead of an inline `role="status"`
  banner.

## Deploy notes
none — frontend-only styling change. No API, schema, or env-var changes.

## Risk / rollback
Low: pure presentational change per page, each page independently
revertible. Verified per page with `pnpm typecheck`, `pnpm lint`, and
targeted Playwright specs (`local-auth-qa.spec.ts`,
`parent-self-service.spec.ts`, and the money-sensitive
`billing-trust-recovery.spec.ts`/`saas-attendance-billing.spec.ts` for the
payments page). Rollback = revert the single page's commit; no
cross-page coupling.
