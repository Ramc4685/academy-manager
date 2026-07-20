# QW6 — Fix local pnpm typecheck (stale .next/types)
Status: TODO
Size: XS · Depends on: none · Tracker: ../TRACKER.md

## Problem
`pnpm typecheck` fails locally when `.next/types` contains generated type files for since-deleted routes; it only passes in fresh CI builds where `.next` is regenerated.

## Current behavior (verified)
- `frontend/tsconfig.json:22` — `"include": [..., ".next/types/**/*.ts"]` (needed for `typedRoutes: true` route-string validation).
- `frontend/package.json` — `"typecheck": "tsc --noEmit"`; nothing regenerates `.next/types` first.
- Next.js is `15.5.18`, which ships the `next typegen` command (regenerates `.next/types` without a full build).

## Implementation steps
1. Change the script: `"typecheck": "next typegen && tsc --noEmit"`.
   - Chosen over excluding `.next/types` because exclusion would silently drop typed-routes checking (`typedRoutes: true` relies on those files).
2. Confirm CI uses the same entry point (grep `.github/workflows` for `typecheck` / `tsc --noEmit`); if CI calls `tsc` directly, point it at `pnpm typecheck` so local and CI stay identical.
3. Note in `frontend/README` or AGENTS.md dev notes only if a doc already documents `pnpm typecheck` behavior (don't add new docs otherwise).

## Verification
- Repro first: delete a scratch route dir after a build, run old `tsc --noEmit` → fails; then with the new script → passes (typegen prunes the stale entry).
- `pnpm typecheck` passes on a clean checkout with no `.next/` at all.
- Intentionally break a `<Link href>` to a nonexistent route → typecheck still fails (typed routes still enforced).
- CI Frontend Static job green.

## Risks / rollback
- `next typegen` adds a few seconds to typecheck. If it misbehaves on this Next minor, fallback is `rm -rf .next/types && next typegen`… or pin-revert the script. Rollback = one-line script revert.

## PR checklist
- [ ] Release note if backend/ or frontend/ changed (per AGENTS.md)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
