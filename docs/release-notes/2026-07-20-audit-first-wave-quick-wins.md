# Audit first-wave quick wins (QW1, QW3, QW6, QW7, QW8, QW9)

PR: #310

## What changed

- **QW1 — pnpm overrides deduped.** Removed the dead `"pnpm"` key from `frontend/package.json`; pnpm 11 ignored it, and the identical security overrides already live in `frontend/pnpm-workspace.yaml`. No resolution change (esbuild 0.28.1, undici 7.28.0, etc. still pinned), lockfile unchanged.
- **QW3 — weak example credentials scrubbed.** `backend/.env.example` now ships `admin@example.com` / `CHANGE_ME` instead of a real email and `Admin@12345`. `import_blno.py` requires `BLNO_COACH_PASSWORD` / `BLNO_PARENT_PASSWORD` (fails fast if unset) instead of hardcoded passwords. `seed_firebase_users.py` uses `*@example.test` emulator emails and `CHANGE_ME` defaults; `seed_local.py` defaults changed to `CHANGE_ME`. Live docs (`auth_testing.md`, the BLNO local runbook) no longer hardcode the weak passwords. Local-only `backend/.env.bak` deleted.
- **QW6 — local typecheck fixed.** `frontend` `typecheck` script is now `next typegen && tsc --noEmit`, so it passes on a working tree with stale `.next/types` (previously only green in fresh CI builds). Typed-routes checking is preserved. CI already calls `pnpm typecheck`, so local and CI stay identical.
- **QW7 — CI coverage gate widened.** The v2 backend tests step now measures `--cov=v2` (was `--cov=v2/shared`) with `--cov-fail-under=86` (measured TOTAL 87.2% across 2,429 tests, minus 1 for platform variance). Contexts, composition, and interfaces now carry an enforced floor.
- **QW8 — `mapRoleToStatus` deduped.** Extracted a typed `roleToChipVariant(role): ChipVariant` helper into `frontend/lib/admin/role-chip.ts`, replacing two byte-identical `any`-returning copies in `admin/users/page.tsx` and `AdminUsersDirectory.tsx`. Mapping unchanged; typing is now live.
- **QW9 — repo-root clutter removed.** Deleted tracked screenshots, scratch HTML, session logs, and old test artifacts from git (`*.png` at root, `output/`, `.playwright-cli/`, `test_reports/`, `Plans.md`, `academy-financial-flows.html`) and added `.gitignore` entries so they can't return. The `test_result.md` scratch index and its CLI (`scripts/dev/test_result.py` + test) are kept — the CLI is live.

## Deploy notes

None. No migrations, no env-var changes, no manual steps. The QW3 seed-script env vars only affect local/emulator seeding, not production. QW7 changes only a CI gate.

## Verification

- Full backend suite with widened coverage: **2,429 passed** in ~114s, `--cov=v2` TOTAL **87.2%** (clears the 86 floor).
- Frontend **typecheck passed** (`next typegen` runs clean) and **lint: 0 errors, 6 pre-existing warnings** (none in changed files).
- `pnpm install` clean — no "Ignoring pnpm options" warning, lockfile unchanged; `esbuild`/`undici` pins verified.
- `git ls-files` confirms no root PNGs / `output/` / `.playwright-cli/` / `test_reports/` remain tracked; previously-untracked staging PNGs are now ignored.

## Risk / rollback

Low — these are config, CI, docs, refactor, and artifact-cleanup changes with no runtime behavior change. QW3's real-data BLNO seed emails in `seed_local.py`/`import_blno.py` and the export-tool test fixture are intentionally left in place (they are the actual academy dataset, out of scope, and would break the BLNO seed). Roll back by reverting the commits; removed artifacts remain in git history.
