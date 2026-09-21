# batch-9c-admin-mobile-lists

PR: #856

## What changed

- Fixes #847 — Built one shared two-line phone row in the design system (`frontend/components/ds/phone-row.tsx`: name + primary status/amount on line 1, secondary facts on line 2, row actions behind a 44x44 menu trigger) and applied it below `md` to Students, Families, Users and Sessions. The layout choice is made in JS (`frontend/lib/use-is-phone.ts`, `matchMedia` at 48rem) instead of `hidden md:block` / `md:hidden` twins, so exactly one layout is mounted, each row stays a single DOM node, and every existing mobile spec that names a row by `data-testid` still resolves it — no e2e selector churn. Desktop fixes bundled in: Lifecycle moved from the clipped trailing column into the Students name cell, Sessions gained a Day column (recurring `days_of_week`, else the weekday read in the session's own timezone) plus a sticky actions column, and All invoices' actions column now uses the shared sticky-action-column classes so it survives 1280px. Phone filter chips/tabs on Students, Families and Users were raised to 44px (desktop sizes untouched). Actions triggers are named with `aria-label` rather than sr-only text, which would have given every `getByText(name)` a second match in the same row.

## Deploy notes

Frontend-only changes. No new migrations, no new environment variables, no backend schema or endpoint changes.

## Risk / rollback

Low. Changes are additive/structural UI fixes (shared responsive phone-row component, desktop column fixes, touch-target sizing) with no data or schema impact. Full backend gate (pytest, ruff check/format, lint-imports, mypy-baseline) and frontend gate (tsc, eslint, `next build --webpack`) pass on the branch. To roll back, revert this PR's merge commit.
