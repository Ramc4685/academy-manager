# DS4 — Migrate the parent surface onto the design system
Status: IN PROGRESS (PR #TBD, 2026-07-23) — waivers, dashboard, children,
requests migrated; progress and payments remain (see below).
Size: L · Depends on: DS1, DS2, DS3 (all merged first) · Tracker: ../TRACKER.md

Final step of DS1→DS4. Hard-gated: tokens (DS1), de-hexed components (DS2), and primitives (DS3) must all exist, otherwise this sweep just relocates hex. 234 of the repo's 404 inline-style occurrences live in these 6 files — highest-leverage cleanup in the frontend.

## Problem
Six parent pages are built almost entirely with inline `style={{...}}` and raw hex instead of tokens/DS components. Verified counts of `style={{` per file (2026-07-20):

| Page | File | Inline styles |
|---|---|---|
| progress | `app/(parent)/parent/progress/page.tsx` | 58 |
| payments | `app/(parent)/parent/payments/page.tsx` | 54 |
| children | `app/(parent)/parent/children/page.tsx` | 43 |
| requests | `app/(parent)/parent/requests/page.tsx` | 40 |
| dashboard | `app/(parent)/parent/dashboard/page.tsx` | 39 |
| waivers | `app/(parent)/parent/waivers/page.tsx` | 24 |

## Current behavior (verified)
- Pages mix `var(--rally-*)` references, raw hex (e.g. `#fecaca`/`#fff5f5`/`#991b1b` in children's cancel dialog at :343-362, `#94a3b8` ×2 in payments), and Tailwind classes.
- Loading/empty/success states are bespoke per page; success feedback is inline `<p role="status">`.
- children/page.tsx already has its ad-hoc dialog migrated to Modal as a DS3 first adopter (do not redo).

## Proposed change
One page per PR, six PRs. Each PR:
1. Replace inline hex/colors with DS1 token classes (or `var(--rally-*)` where a class can't reach, e.g. dynamic values).
2. Replace hand-rolled cards/buttons/status pills with `Card`/`Button`/`Chip` where they match 1:1.
3. Adopt `Skeleton` for loading states, `EmptyState` for empty lists, `Toast` for mutation success (ToastProvider already mounted in `(parent)` layout by DS3).
4. **Behavior identical**: no copy changes, no layout redesign, no data-flow changes. Keep every `data-testid` and `role` attribute — e2e depends on them.

### Recommended order (and why)
**waivers → dashboard → children → requests → progress → payments.**
- Start with **waivers** (smallest, 24 occurrences, read-mostly, directly covered by `saas-parent-waivers.spec.ts`): cheapest place to prove the migration recipe and calibrate PR size.
- **dashboard**, **children**, **requests** next — moderate size, mutation flows covered by `parent-self-service.spec.ts`.
- **progress** (largest at 58) fifth: big but read-only — low behavioral risk, pure style conversion.
- **payments** (54) last: it is the money surface (checkout/autopay entry points); do it after the recipe has been executed five times, with the most reviewer attention. Rationale over "largest first": occurrence count measures effort, not risk — risk concentrates in payments, so it gets maximum accumulated confidence, while the smallest file proves the process.

## Implementation steps (per page PR)
1. `grep -c "style={{" <page>` before; convert top-down; grep after — target < 5 residual (dynamic-only styles).
2. `grep -n "#[0-9a-fA-F]\{3,6\}" <page>` → 0 raw hex after.
3. Swap loading/empty/success per step 3 above; update any e2e text assertions that moved into toasts.
4. Screenshot before/after (mobile 375px + desktop) and attach to PR.

## Files to change
- `frontend/app/(parent)/parent/waivers/page.tsx`
- `frontend/app/(parent)/parent/dashboard/page.tsx`
- `frontend/app/(parent)/parent/children/page.tsx`
- `frontend/app/(parent)/parent/requests/page.tsx`
- `frontend/app/(parent)/parent/progress/page.tsx`
- `frontend/app/(parent)/parent/payments/page.tsx`

## Verification
- Per PR: `pnpm typecheck` · `pnpm lint` · `pnpm e2e`.
- E2E specs covering parent pages (grep-verified in `frontend/e2e/specs/`): `parent-self-service.spec.ts` (children/requests/dashboard flows), `saas-parent-waivers.spec.ts` (waivers), `billing-trust-recovery.spec.ts` + `saas-attendance-billing.spec.ts` (payments surface), `saas-launch-route-matrix.spec.ts` (route smoke incl. parent), `qa-defects.spec.ts`, `tuition-discounts.spec.ts`, `local-auth-qa.spec.ts`/`local-auth-inventory.spec.ts` (local-auth config only). Progress has the thinnest coverage — add a minimal render/smoke assertion to `parent-self-service.spec.ts` in that PR if none exists.
- Visual check per PR: mobile + desktop screenshots, dark-scheme spot check (parent pages inherit `color-scheme: light dark`).

## Risks / rollback
- Risk: e2e assertions on inline success text break when moved to Toast — update spec in same PR, never weaken the assertion.
- Risk: subtle spacing shifts converting px inline styles to Tailwind spacing scale — screenshots gate each PR.
- Rollback: each page is an independent revert; no cross-page coupling.

## PR checklist (each of the 6 PRs)
- [ ] Release note: "Parent <page> migrated to design-system tokens/primitives (no behavior change)."
- [ ] Update `docs/audit/TRACKER.md` DS4 row (track per-page progress in the PR/Issue column, e.g. "waivers #310, dashboard #312, ...")
- [ ] After the sixth PR merges: flip this plan's Status → DONE (PR #NNN, date)
