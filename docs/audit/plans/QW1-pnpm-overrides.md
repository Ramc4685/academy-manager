# QW1 — Re-point pnpm security overrides
Status: DONE (PR #310, 2026-07-20)
Size: XS · Depends on: none · Tracker: ../TRACKER.md

## Problem
pnpm 11 ignores the `"pnpm"` key in `package.json`, so overrides declared there are dead config and CI/install emit an "Ignoring the pnpm options" warning.

## Current behavior (verified)
- `frontend/package.json` has a `"pnpm": { "overrides": { "@grpc/grpc-js": "1.9.16", "esbuild": "0.28.1", "tmp": "0.2.7", "miniflare>ws": "8.21.0", "undici": "^7.28.0" } }` block — ignored by pnpm 11.
- `frontend/pnpm-workspace.yaml` **already contains the identical `overrides:` map** (plus `onlyBuiltDependencies`/`allowBuilds`), which is the supported pnpm 11 location. The security pins are therefore already effective; the remaining work is removing the dead duplicate so the two can never drift.

## Implementation steps
1. Delete the entire `"pnpm"` key from `frontend/package.json`.
2. Diff the deleted block against `frontend/pnpm-workspace.yaml` `overrides:` first; if any entry existed only in `package.json`, copy it into `pnpm-workspace.yaml` before deleting.
3. Run `pnpm install` in `frontend/` — confirm the ignored-options warning is gone and `pnpm-lock.yaml` is unchanged (or only trivially re-serialized).

## Verification
- `cd frontend && pnpm install` → no "Ignoring ... pnpm options" warning, lockfile unchanged.
- `pnpm why esbuild`, `pnpm why undici`, `pnpm why ws`, `pnpm why tmp` → resolved versions still match the pins (esbuild 0.28.1, undici 7.x, ws 8.21.0 under miniflare, tmp 0.2.7).
- `pnpm audit` → no new findings versus current baseline.
- `pnpm build` still passes.

## Risks / rollback
- Near-zero: removing an ignored key. If resolutions unexpectedly change, `git checkout frontend/package.json frontend/pnpm-lock.yaml`.

## PR checklist
- [ ] Release note if backend/ or frontend/ changed (per AGENTS.md)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
