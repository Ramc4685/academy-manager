# fix-ds2-dehex-design-system-components

PR: #NNN

## What changed
Design-system `Button`, `Chip`, and `Card` now use theme token classes
instead of inline hex (no visual change intended). Chip's 30 status hues
are frozen as a `status.*` palette in `frontend/tailwind.config.ts` (the
Tailwind v4 default palette moved to OKLCH and no longer matches the
shipped v3 hex). The unused `dark` boolean props on Button/Chip/Card were
deleted (zero call sites); buttons gained hover/focus-visible states.
Audit item DS2; unblocks DS3.

## Deploy notes
none — frontend-only refactor, no migrations, no env vars.

## Risk / rollback
Colors map 1:1 to the previous hex; only intentional diffs are the new
button hover/focus states and the dropped (dead) chip dark-glow branch.
If anything looks wrong, revert the single PR — no data or API surface
touched.
