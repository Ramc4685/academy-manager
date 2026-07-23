# fix-ds4-parent-migration

PR: #TBD

## What changed
Migrated parent-surface pages off ad-hoc inline `style={{...}}`/raw-hex
styling and onto the Rally design system (tokens from DS1, de-hexed
primitives from DS2, `FormField`/`Skeleton`/`EmptyState`/`Modal`/`Toast`
from DS3). Pure styling convergence — no copy changes, no layout redesign,
no data-flow changes; every `data-testid`/`role` used by e2e is preserved.
Audit item DS4.

4 of the 6 pages land in this PR, in the plan's recommended order
(waivers → dashboard → children → requests). **progress** and
**payments** — the two largest and riskiest pages (58 and 54 inline
styles; payments alone carries 97 raw-hex occurrences as the money
surface) — are deferred to a follow-up PR so this one stays reviewable
and each landed page gets full attention. DS4 tracker/plan Status
reflect **IN PROGRESS**, not DONE.

- `app/(parent)/parent/waivers/page.tsx` — status pills converted to
  `Chip`, panels to `Card`, submit button to `Button`, mutation success
  routed through `Toast` (`useToast`) instead of an inline `role="status"`
  banner.
- `app/(parent)/parent/dashboard/page.tsx` — `var(--rally-*)` inline
  styles converted to Tailwind token classes; the metric-tone and
  action-kind color maps (previously raw-hex `Record`s) converted to
  token-based Tailwind class bundles, mirroring the `Chip` pattern of
  collapsing many semantic variants onto shared classes. Two decorative
  exceptions kept as documented inline hex: the progress-hero
  teal→cobalt gradient and its matching badge/pill accents, which sit
  outside the two-hue (cobalt/volt) token system.
- `app/(parent)/parent/children/page.tsx` — remaining `var(--rally-*)`
  inline styles converted to Tailwind classes; attendance status pills
  converted to `Chip` (present/absent variants); empty state converted
  to `EmptyState`. This page already had `Modal`/`FormField`/`Skeleton`/
  `Toast` adopted as the DS3 first-mover; this PR finishes the styling.
- `app/(parent)/parent/requests/page.tsx` — `var(--rally-*)` inline
  styles and default-Tailwind-palette classes (`bg-red-50` etc.)
  converted to the app's own status tokens; local ad-hoc `EmptyState`
  helper replaced with the DS3 `EmptyState` primitive.

Each page keeps a small number of genuinely dynamic inline styles
(per-child avatar gradients derived from a name hash, a per-activity-item
accent color computed elsewhere, and the two documented hero-gradient
exceptions above) — these are values no single utility class can reach,
per the DS4 plan's own allowance.

## Deploy notes
none — frontend-only styling change. No API, schema, or env-var changes.

## Risk / rollback
Low: pure presentational change per page, each page independently
revertible. Verified per page with `pnpm typecheck`, `pnpm lint`, and
`parent-self-service.spec.ts` (children/requests/dashboard flows) run
against an isolated dev server. Note: an early e2e run against this
worktree's default port showed 5 spurious chromium-mobile failures,
root-caused to Playwright's `webServer.reuseExistingServer` picking up
an unrelated dev server left running by a *different* worktree
(`mystifying-sinoussi-a22520`) rather than this branch's code; re-run
with an isolated port confirmed all 5 pass. Rollback = revert the
individual page's commit; no cross-page coupling.

## Remaining work (tracked, not in this PR)
`app/(parent)/parent/progress/page.tsx` (58 inline styles, read-only —
low behavioral risk) and `app/(parent)/parent/payments/page.tsx` (54
inline styles / 97 raw hex — the money surface, needs the most reviewer
attention) per the DS4 plan's recommended order.
