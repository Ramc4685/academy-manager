# chore-consolidated-dependency-bumps-3

PR: #TBD

## What changed
Consolidates the ten open Dependabot version bumps (backend + frontend) into a
single verified change. Supersedes and closes the individual Dependabot PRs
#414–#423 (Dependabot auto-closes them once `main` contains the bumps).

Backend (`backend/requirements.txt`):
- certifi 2026.4.22 → 2026.7.22 (#419)
- google-auth 2.52.0 → 2.56.3 (#415)
- pandas 3.0.3 → 3.0.5 (#416)
- platformdirs 4.9.6 → 4.11.2 (#414)
- uvicorn 0.25.0 → 0.52.1 (#418)

Frontend (`frontend/package.json`, `frontend/pnpm-lock.yaml`):
- @types/node 26.1.2 → 26.2.0 (#422)
- firebase 12.15.0 → 12.17.1 (#423)
- postcss 8.5.15 → 8.5.26 (#420)
- serwist 9.5.11 → 9.5.12 (#417)
- web-vitals 5.3.0 → 6.1.0 (#421)

No bumps were dropped; all ten are included.

Two bumps were scrutinised beyond the version pin because they cross a large
version distance:

- **uvicorn 0.25.0 → 0.52.1.** Every invocation in the repo is the plain
  `uvicorn backend.v2.main:app --host … --port … [--reload]` form
  (`backend/Dockerfile`, `backend/scripts/docker_entrypoint.sh`,
  `docker-compose.saas-dev.yml`, `scripts/local_test_stack.sh`). There is no
  programmatic `uvicorn.run(...)`, no `uvicorn.Config` construction, and no
  `--loop`/`--http`/`--lifespan` tuning, so no removed or renamed flag is
  reachable. The pinned `h11==0.16.0` satisfies uvicorn 0.52's floor and pip
  resolved the full requirement set without conflict.
- **web-vitals 5.3.0 → 6.1.0 (major).** The only consumer is
  `frontend/lib/pwa/vitals.ts`, which imports the `Metric` type and the
  `onCLS`/`onFCP`/`onINP`/`onLCP`/`onTTFB` reporters. All five remain in the v6
  API surface with unchanged signatures, and `pnpm typecheck` passes against the
  v6 type definitions.

## Deploy notes
None. Dependency bumps only; no schema, env, route, or config changes. The
standard backend (Fly) and frontend (Cloudflare Worker) deploys pick up the new
versions.

## Risk / rollback
Low. Eight of the ten are patch/minor bumps inside the same major. The two
larger jumps (uvicorn, web-vitals) were audited against actual call sites as
described above and both are used only through APIs that survive the upgrade.

Verified locally with the new versions actually installed, not just pinned. A
fresh throwaway virtualenv (`backend/.venv-local`) on Python 3.12.8 — matching
the `python-version: "3.12"` used by `.github/workflows/production.yml` — was
built from the updated `backend/requirements.txt` plus
`backend/requirements-dev.txt`. Pip resolved the full set with no conflicts and
`pip list` confirms certifi 2026.7.22, google-auth 2.56.3, pandas 3.0.5,
platformdirs 4.11.2, uvicorn 0.52.1. Against that environment the full backend
suite `pytest v2/tests -n auto -q` reports **2727 passed, 0 failed**.

On the frontend, the regenerated `pnpm-lock.yaml` installs cleanly and `pnpm
typecheck`, `pnpm lint` (0 errors, 6 pre-existing warnings), and `pnpm build`
all pass.

To roll back, revert this commit to restore the prior pins and the previous
lockfile.
