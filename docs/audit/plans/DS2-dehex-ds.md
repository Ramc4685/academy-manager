# DS2 — De-hex the design-system components
Status: DONE (PR #NNN, 2026-07-20)
Size: S · Depends on: DS1 · Tracker: ../TRACKER.md

Second step of DS1→DS4. Requires DS1 merged (token names/values final). DS3 (new primitives) must not start before this: new primitives should be born on the token classes this plan establishes, and the audit's warning stands — "until fixed, every DS adoption spreads hex."

## Problem
The design system itself hardcodes hex:
- `frontend/components/ds/button.tsx:39-65` — `variantSpec()` returns raw hex per variant (`#2563eb`, `#facc15`, `#0f172a`, `#991b1b`/`#fecaca`, dark-mode `#1e293b`/`#334155`/`#e2e8f0`), applied via `style={inline}` at `:81-92`/`:97` together with size metrics.
- `frontend/components/ds/chip.tsx:20-51` — `CHIP_VARIANTS`: 30 variants × 3 hex each (bg/fg/dot), plus a `dark` boolean that swaps to `rgba(255,255,255,0.05)`/`#e2e8f0` at `:62-65`.
- `frontend/components/ds/card.tsx:14-21` — `dark ? "#0b1220" : "#fff"` bg and `#1e293b`/`#e2e8f0` border via inline style.

## Current behavior (verified 2026-07-20)
- Button has 6 variants; call-site usage across `app/`+`components/`: `secondary` 85, `primary` 52, `danger` 13, `ghost` 8, `volt` 3, `dark` 2 — ~163 explicit `variant=` usages across 36 importing files (`grep -rln 'components/ds/button'`), plus default-variant usages.
- The `dark` boolean prop on `<Button>` has **zero call sites** (`grep -rn '<Button[^>]*dark'` → 0). Chip/Card `dark` props are used (31 `dark` matches inside `components/ds/`; consumers include admin dark-surface panels) — verify per-component before removal.
- All colors bypass Tailwind, so theme-awareness, hover states, and DS1's tokens don't reach these components.

## Proposed change
1. **Button**: replace `variantSpec()` + inline color styles with Tailwind token classes per variant (a `VARIANT_CLASSES: Record<ButtonVariant, string>` map), e.g. `primary: "bg-rally-cobalt-600 text-white ..."`, `volt: "bg-rally-volt-400 text-rally-ink"`, `danger: "bg-white text-red-800 border-red-200"`, `dark: "bg-rally-ink text-white"`, `secondary`/`ghost` using `rally.line`/`rally.ink` + `dark:` classes. Keep the size map as inline style or convert to classes (`h-[38px]` etc.) — size is not color debt; converting is optional. Add hover/focus classes while there (free win: current buttons have no hover color change).
2. **Kill the `dark` boolean prop on Button** (zero call sites — safe delete). For the `secondary`/`ghost` dark appearance, rely on Tailwind `dark:` variants driven by the existing `darkMode: "class"` config; if a dark-on-light-page surface needs it (admin dark panels), document a `variant="secondary-inverse"` instead of a boolean.
3. **Chip**: convert `CHIP_VARIANTS` hex to token classes. The 30 variants collapse to ~7 color families (green/amber/red/slate/blue/yellow/blue-soft) — keep the 30 semantic names but map them to shared class strings. Keep `dark` prop only if consumers exist (verify with `grep -rn "<Chip[^>]*dark" frontend/app frontend/components`); same for Card. If used, reimplement via `dark:`-prefixed classes rather than a branch to different hex.
4. **Card**: `bg-white border-rally-line` / dark: `bg-rally-night-card border-rally-night-line` (tokens added in DS1). Keep `p`/`accent` props (accent stays a style since it's an arbitrary color input — but type it as a token union if feasible).

## Implementation steps
1. Grep Chip/Card `dark` call sites; decide keep-as-classes vs delete per component.
2. Rewrite `button.tsx` (classes map, drop `dark` prop, keep public API otherwise identical — no call-site changes required).
3. Rewrite `chip.tsx`, `card.tsx` on tokens.
4. Visual regression pass (below).

## Files to change
- `frontend/components/ds/button.tsx`
- `frontend/components/ds/chip.tsx`
- `frontend/components/ds/card.tsx`
- (check only) `frontend/components/ds/lane.tsx` and any other `ds/*` file with hex: `grep -rn "#[0-9a-fA-F]\{3,6\}" frontend/components/ds/`

## Verification
- `pnpm typecheck` (will catch any missed `dark` prop usage) · `pnpm lint` · `pnpm e2e` full suite (buttons appear in nearly every spec; chips in admin-students / billing specs).
- **Visual regression check (required)**: before/after screenshots of one page per Button variant — admin/payments (primary+secondary+danger), parent/children (secondary sm), admin sidebar page chrome (dark surfaces), a chip-heavy table (admin/students). Colors must be pixel-identical where tokens map 1:1; only intentional diffs are DS1 contrast values.
- `grep -c "#" frontend/components/ds/button.tsx` → 0 color hex remaining.

## Risks / rollback
- Risk: subtle rendering differences (inline style beats class specificity; some call sites pass `style`/`className` overrides — audit them: `grep -rn "<Button[^>]*style=" frontend/app frontend/components`).
- Risk: Chip `dark` glow (`boxShadow` with dot color at chip.tsx:75) needs a class-based equivalent or a documented drop.
- Rollback: single revert; components keep identical props (minus unused `dark` on Button).

## PR checklist
- [ ] Release note: "Design-system Button/Chip/Card now use theme tokens (no visual change intended)."
- [ ] Update `docs/audit/TRACKER.md` DS2 row
- [ ] Flip this plan's Status → DONE (PR #NNN, date)
