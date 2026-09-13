# Batch 7: pytest timeout backstop

## What changed
- Fixes #550 — added a pytest-level timeout backstop so a hanging test fails fast instead of burning the full 15-minute CI job: pinned `pytest-timeout==2.4.0` in `backend/requirements-dev.txt`, and added `--timeout=120` to `addopts` plus `timeout_method = "thread"` (xdist-safe) in `backend/pyproject.toml`'s `[tool.pytest.ini_options]`.

## Deploy notes
- None. Dev/CI-only dependency and test configuration change; no migrations, no runtime code paths affected.

## Risk / rollback
- Low risk: a hanging test now fails with a `Timeout` error and thread stack traceback at ~120s instead of hanging silently; a legitimately slow test (>120s) would need an explicit per-test `@pytest.mark.timeout(N)` override, but the full 5111-test suite was confirmed to pass under `-n auto` with the new cap in place, so none currently exceed it.
- Rollback: revert this PR (removes the `--timeout=120` addopt, `timeout_method`, and the `pytest-timeout` pin).

PR: #0
