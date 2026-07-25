# fix-ds4-parent-migration-remainder

PR: #350

## What changed
Migrates the final 2 of 6 parent-surface pages off ad-hoc inline
`style={{...}}`/raw-hex styling onto the Rally design system (DS1
tokens, DS3 primitives), completing audit item DS4. Pure styling
convergence — no copy changes, no layout redesign, no data-flow
changes; every `data-testid`/`role` used by e2e is preserved.

- `app/(parent)/parent/progress/page.tsx` (58 inline styles at last
  count) — `var(--rally-*)` inline styles converted to Tailwind token
  classes; `Skeleton` adopted for the notes loading state; `EmptyState`
  adopted for the no-notes-yet state; the skill-status enum-driven
  color map converted to token-based class bundles (mirrors the
  dashboard's metric-tone conversion in PR #330). Two documented
  exceptions kept inline: the per-note left-border accent (hash-derived
  from the note id, mirrors the per-child avatar gradient exception in
  `children/page.tsx`) and the certificate-banner gradient (same
  documented exception as the dashboard's progress-hero gradient).
  Added a minimal render smoke test to `parent-self-service.spec.ts`
  (this page previously had none, per the DS4 plan's own note on thin
  coverage).
- `app/(parent)/parent/payments/page.tsx` (54 inline styles) — the
  money surface, migrated last with maximum reviewer attention per the
  plan. All raw hex converted to Tailwind token classes (`bg-rally-*`,
  `text-status-*`, etc.); the `StatusPill` enum-driven palette converted
  to token-based class bundles. `StatusPill` is deliberately **not**
  swapped for the DS3 `Chip` primitive: `billing-trust-recovery.spec.ts`
  asserts the exact lowercase status text (`getByText("open", { exact:
  true })`), while `Chip` always uppercases its label — swapping
  components here would have silently broken that e2e assertion (or
  worse, gone unnoticed until it did). Two residual inline styles are
  genuinely dynamic and stay: the "Pay balance" CTA's decorative
  volt→amber gradient (documented exception, same pattern as the other
  hero gradients) and the per-invoice `opacity` toggle for paid/void
  invoices.

## Deploy notes
none — frontend-only styling change. No API, schema, or env-var
changes. No payment logic touched.

## Risk / rollback
Low for progress (read-only page); payments received the most careful
review of the six pages per the plan's own risk ordering — every
button's `onClick`/`disabled`/type and every status pill's exact text
were left byte-identical, only the styling layer changed. Verified per
page with `pnpm typecheck`, `pnpm lint`, and targeted e2e runs
(`parent-self-service.spec.ts`, `billing-trust-recovery.spec.ts`,
`saas-launch-route-matrix.spec.ts`) against an isolated dev server
port. Two unrelated failures surfaced in the full route-matrix run
(`admin dashboard`, `coach today`) — both on files untouched by this
PR, consistent with the same cold-compile-under-parallelism flakiness
documented in PR #330's release notes; all payments/progress-specific
assertions passed. Rollback = revert this PR; no cross-page coupling.

## DS4 completion
This PR completes DS4 — all 6 parent pages (waivers, dashboard,
children, requests, progress, payments) are now migrated onto the
design system. `docs/audit/TRACKER.md`'s DS4 row and
`docs/audit/plans/DS4-parent-migration.md`'s Status line are updated to
DONE in this same PR.
