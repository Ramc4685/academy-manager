# DS1 — Single-source color tokens + contrast fixes
Status: DONE (PR #313, 2026-07-20)
Size: S · Depends on: none · Tracker: ../TRACKER.md

First step of the ordered DS1→DS4 design-standardization sequence. DS2 (de-hex the DS components) must not start until this merges, because DS2 converts hex to the token names this plan finalizes.

## Problem
The Rally palette is defined three times and has drifted into raw hex:
1. `frontend/tailwind.config.ts:26-47` — `rally.*` Tailwind colors (ink/paper/line/muted/subtle + cobalt/volt scales).
2. `frontend/app/globals.css:31-40` — `--rally-*` CSS variables duplicating the same hex values by hand (plus a legacy `--academy-*` block at :21-28).
3. Raw hex sprinkled through components — e.g. `app/(admin)/layout.tsx:154` (`#0a0f1c` sidebar bg), `:189`/`:277` (`#64748b` 9px micro-text), `:211` (`#475569` 9px group labels), `:231` (`#94a3b8` inactive nav text).

Two verified WCAG AA failures ride on these values:
- `#94a3b8` (rally-subtle) as body/label text on light surfaces (`#fff`/`#f8fafc`) ≈ 2.9:1 — fails 4.5:1.
- Admin sidebar micro-text `#475569` (≈2.6:1) and `#64748b` (≈3.8:1) on `#0a0f1c` at 9px mono — fails 4.5:1 for small text.

## Current behavior (verified 2026-07-20)
- `tailwind.config.ts` and `globals.css` carry identical hex values maintained independently (e.g. `#94a3b8` appears as `rally.subtle` and `--rally-subtle`).
- Occurrence counts across `app/ components/ lib/` (grep, case-insensitive):
  - `#94a3b8` — 12 occurrences in 6 files: `components/ds/chip.tsx` (5: dot colors for waived/nocharge/paused/transferred/draft), `app/(parent)/parent/payments/page.tsx` (2), `app/(admin)/layout.tsx` (2: inactive NavRow text :231, mobile-drawer twin), `components/ds/lane.tsx` (1), `app/(admin)/admin/waivers/page.tsx` (1), `app/(admin)/admin/students/page.tsx` (1).
  - `#475569` — 5 occurrences (admin layout group labels, chip.tsx `expired`/`draft` fg, scattered).
  - `#64748b` — 14 occurrences (admin layout micro-text ×2 at :189/:277 + drawer twins, chip.tsx dots, misc pages).
- Missing from the palette entirely: the dark-surface family used by the admin shell — `#0a0f1c` (sidebar bg), `#1e293b` (borders/active row), `#101a2e` (user pill), `#0b1220` (Card dark bg), `#cbd5e1` (sidebar body text).

## Proposed change
1. **`tailwind.config.ts` is the single source of truth.** Extend `rally` with the missing dark-surface family: `night: "#0a0f1c"`, `night-line: "#1e293b"`, `night-panel: "#101a2e"`, `night-card: "#0b1220"`, `bright: "#cbd5e1"`.
2. **Derive `--rally-*` vars from the config** (Tailwind v4 is already in use — `@config` in globals.css). Either delete the hand-copied `:root` block and rely on Tailwind v4's generated `--color-rally-*` vars, or keep the `--rally-*` aliases but define each as `var(--color-rally-*)` so there is exactly one hex per color in the repo. Keep the `--academy-*` block untouched (marketing/legacy pages) but add a `/* deprecated — do not use in new code */` comment.
3. **Contrast fix A — rally-subtle on light:** change `rally.subtle` from `#94a3b8` to **`#64748b`** (slate-500) wherever it is used as *text on light backgrounds*. Ratio: `#64748b` on `#ffffff` = **4.76:1**, on `#f8fafc` ≈ **4.6:1** — both pass AA 4.5:1. `#94a3b8` remains valid as a *non-text* color (chip dots, decorative lanes) — rename that usage to `rally.subtle-ink` or reference it as `rally.slate-400` so the lint story is "subtle is never text on light."
4. **Contrast fix B — sidebar micro-text on `#0a0f1c`:** lighten both 9px values to **`#94a3b8`**: on `#0a0f1c` that is ≈ **7.1:1** — passes AA (and AAA 7:1) at any size. Concretely: `(admin)/layout.tsx:189` and `:277` `#64748b` → `#94a3b8`; `:211` group-label `#475569` → `#94a3b8` (or `#7c8aa0` ≈ 5.2:1 if a dimmer hierarchy step is wanted between labels and values). Inactive nav text `#94a3b8` at :231 already passes (7.1:1) — leave value, tokenize only.
5. Replace the raw-hex offenders in `(admin)/layout.tsx` (both desktop sidebar and mobile drawer twins) with the new token classes/vars. Full de-hexing of the rest of the app is DS2 (DS components) and DS4 (parent pages) — do not sweep here.

## Implementation steps
1. Extend `rally` palette in `tailwind.config.ts` (night family, adjusted `subtle`).
2. Rewrite `globals.css:31-40` to alias generated vars (or delete block + update `components/ds/*` consumers of `var(--rally-*)` — grep first: `grep -rn "var(--rally" frontend/components frontend/app`).
6. Apply contrast fixes + tokenization in `app/(admin)/layout.tsx` (lines 154, 156, 173, 177, 181, 189, 211, 229-235, 243-244, 267, 270, 277 and the mobile-drawer equivalents further down the file).
4. Update the 6 `#94a3b8` consumer files listed above only where the value is *text on light* (parent/payments ×2, admin/waivers ×1, admin/students ×1). Chip dots and lane.tsx are decorative — leave for DS2.
5. Run visual spot-check (admin sidebar desktop + drawer, parent payments) before/after.

## Files to change
- `frontend/tailwind.config.ts`
- `frontend/app/globals.css`
- `frontend/app/(admin)/layout.tsx`
- `frontend/app/(parent)/parent/payments/page.tsx`
- `frontend/app/(admin)/admin/waivers/page.tsx`
- `frontend/app/(admin)/admin/students/page.tsx`
- (read-only check) `frontend/components/ds/*.tsx` for `var(--rally-*)` consumers

## Verification
- `pnpm typecheck` · `pnpm lint` · `pnpm e2e` (admin-shell.spec.ts exercises the sidebar nav testids — unchanged).
- Visual: screenshot admin sidebar (desktop 1280px + mobile drawer) and parent payments; confirm micro-text legibility and no palette shift elsewhere.
- Contrast: re-run ratios for the two fixes (e.g. `npx wcag-contrast` or any checker): `#64748b`/`#f8fafc` ≥ 4.5, `#94a3b8`/`#0a0f1c` ≥ 4.5.
- `grep -rn "#94a3b8\|#475569" frontend/app/\(admin\)/layout.tsx` returns nothing.

## Risks / rollback
- Risk: rally-subtle darkening is a global visual change (12 sites) — mostly desirable (it was failing AA), but review screenshots; chip dots intentionally unchanged.
- Risk: deleting the `--rally-*` block breaks `components/ds/*` if any consumer is missed — the alias approach (keep names, point at generated vars) is the safe default.
- Rollback: single revert; no data or API surface touched.

## PR checklist
- [ ] Release note: "Admin sidebar and secondary text meet WCAG AA contrast; Rally palette now single-sourced in tailwind.config.ts."
- [ ] Update `docs/audit/TRACKER.md` DS1 row (Status, PR#)
- [ ] Flip this plan's Status → DONE (PR #NNN, date)
