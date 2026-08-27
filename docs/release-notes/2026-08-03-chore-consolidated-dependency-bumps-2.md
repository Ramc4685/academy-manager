# chore-consolidated-dependency-bumps-2

PR: #399

## What changed
Consolidates the open Dependabot version bumps (backend + frontend) into one
green change, including the `librt` bump the `mypy` upgrade requires. Supersedes
and closes the individual Dependabot PRs #384–#388, #390–#393. (#389,
`@fullcalendar/react` 6→7, is a breaking major bump that needs its sibling
`@fullcalendar/*` packages migrated together and is left open separately.)

Backend (`backend/requirements.txt`, `backend/requirements-dev.txt`):
- tqdm 4.68.3 → 4.70.0 (#384)
- jq 1.11.0 → 1.12.0 (#385)
- sentry-sdk[fastapi] 2.66.0 → 2.66.1 (#386)
- resend 2.30.1 → 2.35.0 (#387)
- mypy 2.1.0 → 2.3.0 (#388)
- librt 0.11.0 → 0.13.0 — not itself a Dependabot PR; bumped alongside mypy
  because mypy 2.3.0 requires `librt>=0.13.0` and pip's resolver fails
  otherwise (`ResolutionImpossible`)

Frontend (`frontend/package.json`):
- @radix-ui/react-slot 1.3.0 → 1.3.3 (#393)
- @serwist/next 9.5.11 → 9.5.12 (#391)
- recharts 3.9.1 → 3.10.1 (#392)
- wrangler 4.100.0 → 4.114.0 (#390)

## Deploy notes
None. Dependency bumps only; no schema, env, or config changes. Standard
backend + frontend deploy picks up the new versions.

## Risk / rollback
Low. All are patch/minor bumps within the same majors, plus the librt bump
which is a transitive requirement of the mypy dev-tool bump (not shipped to
runtime images). Verified locally: backend `ruff check`/`ruff format --check`
clean, `mypy --config-file backend/pyproject.toml -p backend.v2 | mypy-baseline
filter` reports 0 new errors against the frozen baseline; frontend `pnpm
typecheck`, `pnpm lint`, and `pnpm build` all pass. To roll back, revert this
commit to restore the prior pins.
