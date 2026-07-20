# C1 — Un-break the mypy gate
Status: DONE (PR #311, 2026-07-20) — shipped via Alternative B: deleting `backend/__init__.py` does NOT fix the abort (`explicit_package_bases` makes `__init__.py` irrelevant to module-name mapping); fix = repo-root invocation `-p backend.v2` with `files`/`mypy_path` removed. 376 stale ignores stripped; 559 errors frozen with mypy-baseline (burn-down: ../mypy-baseline.md).
Size: M · Depends on: none · Tracker: ../TRACKER.md

## Problem

Mypy checks zero files. CI runs it (`.github/workflows/production.yml:165-168`) but the invocation aborts immediately with "Source file found twice under different module names", and the step carries `continue-on-error: true`, so the failure has been invisible. The type gate the repo claims to have (`strict = true`, `backend/pyproject.toml:25`) does not exist in practice. Once the config is fixed, there is a backlog of roughly 937 strict-mode errors (possibly ~560 depending on invocation path) that must be triaged before the gate can be made blocking.

Root cause (two interacting facts):

1. `backend/__init__.py` exists, is tracked, and is empty (0 bytes) — it makes `backend/` a regular package.
2. `backend/pyproject.toml:23-32` sets both `mypy_path = ".."` (line 29) and `files = ["v2"]` (line 26) with `explicit_package_bases = true`. Run from `backend/` (CI does `working-directory: backend`), every file under `v2/` is discoverable both as `v2.<mod>` (base = cwd) and as `backend.v2.<mod>` (base = `..`), because `backend/__init__.py` marks `backend` as a package rooted at `..`. Mypy aborts on the first duplicate.

## Current behavior (verified)

`backend/pyproject.toml:23-32`:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
files = ["v2"]
exclude = ["legacy", "scripts", "tests"]
plugins = ["pydantic.mypy"]
mypy_path = ".."
namespace_packages = true
explicit_package_bases = true
```

`.github/workflows/production.yml:165-168` (job `backend-advisory`, `working-directory: backend`):

```yaml
- name: Mypy v2
  working-directory: backend
  continue-on-error: true
  run: mypy --config-file pyproject.toml v2
```

`backend/__init__.py`: tracked, 0 bytes.

Consumers of the `backend` package name (all must keep working after the fix):

- Runtime: `backend/Dockerfile:11,14` — `ENV PYTHONPATH="/app:/app/backend"` and `CMD ["uvicorn", "backend.v2.main:app", ...]`. All of `backend/v2/` imports via absolute `from backend.v2....` paths.
- Tests: `backend/pyproject.toml:41` — `[tool.pytest.ini_options] pythonpath = [".."]` puts the repo root on `sys.path` so `backend.v2.*` resolves.
- Import-linter: `backend/pyproject.toml:64` — `root_packages = ["backend"]` (grimp builds the graph from the `backend` package).
- Scripts: `scripts/dev/seed_blno_staging.py`, `scripts/dev/seed_badminton_pathway.py`, `scripts/local_test_stack.sh`, etc. import `backend.*` with the repo root on `PYTHONPATH`.
- CI: `backend-advisory` and `backend-tests` jobs export `PYTHONPATH: ${{ github.workspace }}`.

## Proposed change

**Delete `backend/__init__.py`.** `backend` becomes an implicit namespace package (PEP 420, native since Python 3.3; the repo targets 3.12). Every consumer above resolves `backend.v2.*` via `sys.path` entries pointing at the repo root, which works identically for namespace packages:

- `uvicorn backend.v2.main:app` — resolves through `/app` on `PYTHONPATH`; namespace packages import fine. No Dockerfile change.
- pytest / scripts / CI — same: path-based resolution, unaffected.
- import-linter/grimp — modern grimp resolves namespace packages; this is the one consumer to verify empirically (step 3). If `lint-imports` breaks, fall back to Alternative B below rather than restoring the file blindly.

With `backend/__init__.py` gone, mypy (with `namespace_packages = true` + `explicit_package_bases = true`, already set) maps each file under `v2/` to exactly one module name per base and the duplicate-detection abort disappears.

**Alternative B (only if deletion breaks a consumer):** keep `backend/__init__.py`, drop `mypy_path = ".."` from `backend/pyproject.toml`, and change the CI/local invocation to run from the repo root: `mypy --config-file backend/pyproject.toml -p backend.v2` with `files` removed. This keeps one unambiguous base. Do not ship both fixes together.

**Backlog strategy (staged, so the gate becomes blocking early):**

The ~937 errors do not need to be fixed before removing `continue-on-error`. Instead, freeze the baseline and block only *new* errors, then burn the backlog in per-error-code waves.

## Implementation steps

1. `git rm backend/__init__.py`.
2. Sanity-check nothing regular-package-dependent breaks locally:
   - `cd backend && python -c "import backend.v2.main"` with `PYTHONPATH=..` — must import.
   - `cd backend && pytest v2/tests -x -q` (or at minimum a fast subset) — pytest `pythonpath=[".."]` path.
3. Verify import-linter still builds the graph: `cd backend && lint-imports --config pyproject.toml`. If grimp errors on the namespace package, revert step 1 and switch to Alternative B.
4. Confirm mypy now runs: `cd backend && mypy --config-file pyproject.toml v2 2>&1 | tail -5`. Expect a real error summary ("Found N errors in M files"), not the "found twice" abort. Record N — this is the baseline count.
5. Verify uvicorn module resolution in the container path: `docker build -f backend/Dockerfile .` and run it (or rely on the staging deploy smoke) — `backend.v2.main:app` must boot. (Low risk: PEP 420 covers it; this step is confirmation.)
6. Baseline the backlog. Two supported mechanisms — pick one:
   - Preferred: generate a suppression baseline with `mypy ... | mypy-baseline` (add `mypy-baseline` to dev deps) or
   - Zero-tooling: capture per-error-code counts (`mypy ... | grep -oE '\[[a-z-]+\]$' | sort | uniq -c | sort -rn`) into `docs/audit/mypy-baseline.md`, and add temporary `disable_error_code = [...]` entries in `[tool.mypy]` for the top offending codes so the run is green.
7. Remove `continue-on-error: true` from `.github/workflows/production.yml:167`. The mypy step is now blocking at the frozen baseline.
8. Burn-down waves (separate follow-up PRs, one error code per PR): re-enable one `disable_error_code` entry (or shrink the baseline file), fix that wave, repeat. Suggested order: `no-untyped-def` / `no-untyped-call` first (mechanical), then `assignment`/`arg-type`, leaving `misc`/`type-arg` last.
9. Update `AGENTS.md` if it documents the type-check command, and note the new local command: `cd backend && mypy --config-file pyproject.toml v2`.

## Files to change

- `backend/__init__.py` (delete)
- `.github/workflows/production.yml` (remove `continue-on-error` at :167; possibly adjust invocation if Alternative B)
- `backend/pyproject.toml` (only if baseline uses `disable_error_code`, or if Alternative B)
- `backend/requirements.txt` (only if adopting `mypy-baseline`)
- `docs/audit/mypy-baseline.md` (new, if using the zero-tooling baseline)

## Tests & verification

```bash
cd backend
PYTHONPATH=.. python -c "import backend.v2.main"
pytest v2/tests --override-ini="testpaths=v2/tests" -q
lint-imports --config pyproject.toml
mypy --config-file pyproject.toml v2 2>&1 | tail -5   # must NOT say "found twice"
ruff check v2
```

No new tests — this is a gate fix; the verification is that mypy produces a real error report and CI fails when a new type error is introduced (can be spot-checked by pushing a deliberate `x: int = "a"` to a draft branch).

Log per AGENTS.md: `scripts/dev/test_result.py log` recording that the mypy gate config changed and what was re-verified.

## Risks / rollback

- **grimp/import-linter can't handle the namespace package** → caught at step 3 before merge; use Alternative B.
- **Some consumer imports `backend` in a way that requires a regular package** (e.g. relies on `backend.__file__`) → grep showed only absolute-import usage, but if something surfaces, restore the file and use Alternative B.
- **Baseline freeze hides a genuine bug class** → the baseline is temporary by design; each wave PR shrinks it, and the count is tracked in the baseline doc.
- Rollback: `git revert` — restoring the empty `__init__.py` and the `continue-on-error` line returns to the (broken but inert) status quo. No data or runtime behavior involved.

## PR checklist

- [ ] Release note in docs/release-notes/ (per AGENTS.md)
- [ ] TRACKER.md status updated
- [ ] This plan's Status line flipped to DONE
