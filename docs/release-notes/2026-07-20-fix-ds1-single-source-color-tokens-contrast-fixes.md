# DS1 — Single-source color tokens + contrast fixes

**Date:** 2026-07-20
**Branch:** `fix/DS1-tokens`
**Audit item:** DS1 (docs/audit/plans/DS1-tokens.md)

## What changed

- Admin sidebar and secondary text meet WCAG AA contrast; the Rally palette is now single-sourced in `frontend/tailwind.config.ts`.
- `rally.subtle` darkened `#94a3b8` → `#64748b` for text on light surfaces (4.76:1 on white, 4.55:1 on paper — both pass AA 4.5:1). The old value survives as the new `rally.subtle-ink` token, restricted to decorative marks and text on dark "night" surfaces.
- Admin sidebar 9px micro-text (brand tagline, nav group labels, user-pill role) lightened from `#475569`/`#64748b` to `#94a3b8` on the `#0a0f1c` sidebar — 7.46:1, passes AA and AAA at any size. Applies to both the desktop sidebar and the mobile drawer (shared components).
- New dark-surface tokens added to the palette: `rally.night` (#0a0f1c), `night-line` (#1e293b), `night-panel` (#101a2e), `night-card` (#0b1220), `bright` (#cbd5e1).
- `globals.css` `--rally-*` variables are no longer hand-copied hex: each is derived from the Tailwind config via `theme()` at build time, so every Rally color has exactly one hex definition in the repo. (Note: Tailwind v4's `@config` compat does **not** emit `--color-rally-*` vars, so the plan's `var(--color-rally-*)` alias option was replaced with `theme()` derivation.) The legacy `--academy-*` block is marked deprecated.
- Raw palette hex removed from `app/(admin)/layout.tsx`; `#94a3b8` literals tokenized in parent payments (dark balance hero — already-passing 7.46:1, tokenized not darkened), admin waivers, and admin students card accents.

## Out of scope (per plan)

- Chip dot colors and lane.tsx decorative hex → DS2.
- Full de-hex of DS components → DS2; parent pages → DS4.
- Marketing/landing CSS modules untouched.

## Verification

- `pnpm typecheck`, `pnpm lint`, `pnpm e2e` green.
- Contrast ratios recomputed: subtle 4.76:1 (white) / 4.55:1 (paper); sidebar micro-text 7.46:1; inactive nav icons 4.02:1 (≥3:1 non-text).
- Visual spot-check: admin sidebar (desktop + drawer) and parent payments.
