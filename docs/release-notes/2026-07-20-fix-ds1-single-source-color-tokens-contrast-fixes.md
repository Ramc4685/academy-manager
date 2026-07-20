# fix-ds1-single-source-color-tokens-contrast-fixes

PR: #313

## What changed
Admin sidebar and secondary text now meet WCAG AA contrast, and the Rally
palette is single-sourced in `frontend/tailwind.config.ts` (globals.css
`--rally-*` vars derive from it via `theme()`). `rally.subtle` darkened to
`#64748b` for text on light surfaces; the old `#94a3b8` lives on as
`rally.subtle-ink` for decorative/dark-surface use, including the new
`rally.night*` admin-shell tokens. Audit item DS1; unblocks DS2→DS4.

## Deploy notes
none — frontend-only visual change, no migrations, no env vars.

## Risk / rollback
Secondary text across admin/parent/coach pages renders slightly darker
(intended AA fix); admin sidebar micro-labels render lighter. If anything
looks wrong, revert the single PR — no data or API surface touched.
