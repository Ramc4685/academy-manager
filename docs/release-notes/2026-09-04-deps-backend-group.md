# deps-backend-group

PR: #648

## What changed
Dependabot's grouped backend bump (25 packages in `backend/requirements.txt` and
`backend/requirements-dev.txt`) is merged and made installable. The raw Dependabot diff
paired `pydantic==2.13.5` with `pydantic_core==2.48.0`, but no published `pydantic`
release requires `pydantic_core` 2.48.0 (only the `2.14.0b1` pre-release does, per
PyPI metadata) — `pydantic==2.13.5` pins `pydantic_core==2.46.5` exactly, so `pip`
raised `ResolutionImpossible`. `pydantic_core` is repinned to `2.46.5` to match the
version `pydantic==2.13.5` actually requires; every other package in the group
(`click`, `cryptography`, `filelock`, `google-api-python-client`, `google-auth`,
`grpcio`/`grpcio-status`, `importlib_metadata`, `openai`, `platformdirs`, `proto-plus`,
`protobuf`, `regex`, `resend`, `stripe`, `typer`, plus dev-only `import-linter`,
`isort`, `pytest-asyncio`, `ruff`) is unchanged from Dependabot's proposal. Branch was
also brought up to date with `main` (27 commits: #661/#662/#664/#665/#666 and follow-ups
through #685/#686) — no requirements conflicts from that merge.

## Deploy notes
None. Dependency-only change, no migration, no new env vars, no behavior change.
`pip install -r backend/requirements.txt -r backend/requirements-dev.txt` was proven to
resolve cleanly in a scratch Python 3.12 venv (matching CI's `setup-python` version).

## Risk / rollback
Verified against CI's own lint and test gates before merge: `ruff check v2` and
`ruff format --check v2` pass clean; `mypy --config-file backend/pyproject.toml -p
backend.v2` piped through `mypy-baseline filter --allow-unsynced` reports 0 new errors
(101 pre-existing baseline entries even resolved, none introduced); the full `v2/tests`
suite was run locally against a real `mongod` instance with the CI env vars. Risk is
limited to patch/minor bumps within packages already pinned exact-version; no major
version jumps in the group. Rollback is reverting the dependency commit (or re-opening
the Dependabot PR) if a runtime regression surfaces post-deploy.
