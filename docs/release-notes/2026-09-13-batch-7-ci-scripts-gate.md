# batch-7-ci-scripts-gate

PR: #814

## What changed

- Fixes #535 — Closed the `scripts/**` CI blind spot: `.github/workflows/production.yml`'s `dorny/paths-filter` had no `scripts` key, so edits to `local_test_stack.sh`, `production_smoke.sh`, and `publish_release.py` merged without any validation and only surfaced failures at deploy/release time. Added a `scripts: ['scripts/**']` filter entry and a corresponding `scripts` output on the `changes` job, then added a new lightweight `scripts-validate` job that runs `shellcheck -S error` over `scripts/**/*.sh`, `py_compile` over `scripts/**/*.py`, and `actionlint` over the workflow YAML itself. The job is gated the same way as the other validation jobs (runs when `scripts`/CI files change, on `workflow_dispatch`, or on push to `main`) and is added to `ci-gate`'s `needs`, so a failure now blocks merge instead of surfacing later. The existing broken/unwired `scripts/dev/tests/test_release_automation.py` test was deliberately left out of the new job — it fails identically on `main` today, unrelated to this issue — and a follow-up task was filed instead of silently absorbing an out-of-scope bug.

## Deploy notes

No migrations. CI-only change to `.github/workflows/production.yml`; no runtime env var or app config changes.

## Risk / rollback

Additive CI gating only — no application code paths changed. Worst case is a false-positive lint/shellcheck failure blocking an unrelated PR that happens to touch `scripts/**`; revert this PR's merge commit to restore the previous (unvalidated) behavior if that happens.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
