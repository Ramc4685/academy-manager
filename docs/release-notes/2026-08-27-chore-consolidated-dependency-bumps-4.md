# chore-consolidated-dependency-bumps-4

PR: #446

## What changed
Second consolidation round for the day. After #444 landed, Dependabot opened
four fresh bumps on top of it; each individually fails the release-notes `check`
gate because Dependabot cannot author a release note. This rolls all four into
one change that carries its own note. Supersedes and closes #414, #418, #421,
and #423 (Dependabot auto-closes them once `main` contains the bumps).

Backend (`backend/requirements.txt`):
- platformdirs 4.11.2 → 4.11.4 (#414)
- uvicorn 0.52.1 → 0.52.4 (#418)

Frontend (`frontend/package.json`, `frontend/pnpm-lock.yaml`):
- firebase 12.17.1 → 12.18.0 (#423)
- web-vitals 6.1.0 → 6.2.0 (#421)

Nothing was dropped; all four are included.

All four are patch/minor bumps sitting directly on top of the versions already
validated in #444, so no fresh API-surface audit was warranted. The two jumps
that did need scrutiny — uvicorn 0.25 → 0.52 and the web-vitals 5 → 6 major —
were audited against their real call sites in #444 and are unchanged here:
uvicorn is still only invoked as `uvicorn backend.v2.main:app --host … --port …
[--reload]` with no programmatic `Config` or loop/http tuning, and web-vitals'
only consumer (`frontend/lib/pwa/vitals.ts`) still uses just the `Metric` type
plus `onCLS`/`onFCP`/`onINP`/`onLCP`/`onTTFB`, all stable within v6.

## Deploy notes
None. Dependency bumps only; no schema, env, route, or config changes. The
standard backend (Fly) and frontend (Cloudflare Worker) deploys pick up the new
versions.

## Risk / rollback
Low. Every bump is a patch or minor release inside a major already running in
this repo.

Verified with the new versions actually installed, not merely pinned. The
throwaway Python 3.12.8 virtualenv (`backend/.venv-local`) — matching the
`python-version: "3.12"` used by `.github/workflows/production.yml` — was
reinstalled from the updated `backend/requirements.txt` plus
`backend/requirements-dev.txt`; pip resolved with no conflicts and `pip list`
confirms platformdirs 4.11.4 and uvicorn 0.52.4. Against that environment the
full backend suite `pytest v2/tests -n auto -q`, run from `backend/`, reports
**2806 passed, 0 failed**.

On the frontend, the regenerated `pnpm-lock.yaml` installs cleanly and `pnpm
typecheck`, `pnpm lint` (0 errors, 6 pre-existing warnings), and `pnpm build`
all pass.

To roll back, revert this commit to restore the prior pins and the previous
lockfile.
