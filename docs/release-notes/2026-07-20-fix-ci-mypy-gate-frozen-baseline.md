# fix-ci-mypy-gate-frozen-baseline

PR: #311

## What changed

The backend type-check gate (audit item C1) now actually runs: mypy previously
aborted on its first file ("source file found twice") and CI hid that behind
`continue-on-error`, so `strict = true` checked nothing. Mypy now runs from the
repo root (`-p backend.v2`), 376 stale `# type: ignore` comments were removed
(verified behavior-identical), and the remaining 559 pre-existing strict errors
are frozen in `backend/mypy-baseline.txt`. The CI step is blocking: any NEW
type error fails the build; burn-down of the frozen backlog is tracked in
`docs/audit/mypy-baseline.md`.

## Deploy notes

None — CI/tooling and comment-only source changes; no runtime behavior, no
migration, no env vars. `mypy-baseline==0.7.4` added to backend dev
dependencies. New local command (repo root):
`mypy --config-file backend/pyproject.toml -p backend.v2 | mypy-baseline filter --baseline-path backend/mypy-baseline.txt`.

## Risk / rollback

If the gate misfires (e.g. an environment-dependent error not in the baseline),
PRs fail CI on the Mypy step with the offending error printed; fix the error or
re-sync the baseline deliberately. Revert the merge commit to restore the old
advisory (broken) gate — no data or runtime impact.
