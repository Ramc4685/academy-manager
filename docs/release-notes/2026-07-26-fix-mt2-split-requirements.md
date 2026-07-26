# fix-mt2-split-requirements

PR: #356

## What changed
Split `backend/requirements.txt` into a runtime-only file and a new
`backend/requirements-dev.txt` (test/lint tooling). Dropped six confirmed-unused
packages (`boto3`, `huggingface_hub`, `tokenizers`, `tiktoken`, `google-genai`,
`hf-xet`) plus their orphaned transitive deps (`botocore`, `s3transfer`), which
only existed to serve `boto3`. Updated CI (`production.yml`) to install/cache
`requirements-dev.txt` in the `backend` and `backend-advisory` jobs, while the
`pip-audit` step keeps auditing the runtime file. Updated the local dev-setup
hint in `scripts/dev/pre-push-checks.sh`.

## Deploy notes
None — `backend/Dockerfile` is unchanged and still installs only
`backend/requirements.txt` (now the trimmed runtime file), so the production
image gets smaller with no build-step changes. No migrations, no env vars.

## Risk / rollback
Risk is limited to CI/dev tooling: if `requirements-dev.txt` is missing a pin,
`pytest`/`ruff`/`mypy` steps in CI fail, not production. Verified locally: a
fresh venv from the trimmed `requirements.txt` boots `backend.v2.main` cleanly
and `pip check` is clean in both venvs; a fresh venv from
`requirements-dev.txt` passes the full `v2/tests` suite (2,587 tests), `ruff
check`/`ruff format --check`, `lint-imports`, and the mypy baseline gate (0 new
violations) under Python 3.12. Rollback: revert this PR to restore the single
frozen `requirements.txt`.
