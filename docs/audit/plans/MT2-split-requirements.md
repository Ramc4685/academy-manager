# MT2 — Split runtime vs dev requirements

Status: DONE (PR #TBD, 2026-07-26)
Size: S · Depends on: none · Tracker: ../TRACKER.md

## Problem

`backend/requirements.txt` is a 135-package pip-freeze (verified: `grep -c '==' backend/requirements.txt` → 135) installed wholesale into the production image. It mixes runtime deps with dev/test tooling and several packages with **zero imports anywhere in the repo** (they arrived transitively via a since-removed dependency and got frozen).

## Current behavior (verified 2026-07-20)

- Confirmed-unused in first-party code (only hits are inside `backend/.venv/`): `boto3` (requirements.txt:12), `huggingface_hub` (:45), `tokenizers` (:123), `tiktoken` (:122), `google-genai` (:36), `hf-xet` (:41).
- Dev-only tools pinned in the same file: `black` (:11), `flake8` (:29), `isort` (:50), `ruff` (:113), `mongomock-motor` (:93), `pytest` (:94), `pytest-asyncio` (:95), `pytest-cov` (:96), `pytest-xdist` (:97).
- `backend/Dockerfile:5-6`:
  ```
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  ```
- CI (`.github/workflows/production.yml`): the `backend` job installs `requirements.txt` (:108), then runs `pip-audit -r requirements.txt --ignore-vuln PYSEC-2026-1325` (:115), `lint-imports` (:123), `pytest v2/tests ... --cov` (:127). The `backend-advisory` job installs `requirements.txt` (:155), runs `ruff check`/`ruff format --check` (:159, :163) and `mypy` (:168). Both jobs cache on `backend/requirements.txt` (:102, :149). So CI **depends on the dev tools being installed** — they must move to a dev file that CI installs, not be deleted.

## Proposed change

Split into:
- `backend/requirements.txt` — runtime only (what the Docker image needs to boot and serve).
- `backend/requirements-dev.txt` — starts with `-r requirements.txt`, then dev/test tools.
- Drop the six confirmed-unused packages entirely (plus any orphaned transitive-only pins that `pip check` no longer requires — e.g. `hf-xet` exists only for `huggingface_hub`).

## Implementation steps

1. **Verify each removal has zero first-party imports.** For every candidate `<pkg>` (import name = pkg with `-`→`_`; `google-genai` imports as `google.genai`):
   ```bash
   cd /Users/ramc/Documents/Code/academy-manager
   grep -rn --include='*.py' -E "^\s*(import|from)\s+(boto3|huggingface_hub|tokenizers|tiktoken|hf_xet)\b" backend scripts | grep -v '\.venv'
   grep -rn --include='*.py' -E "from google(\.| )genai|import google\.genai" backend scripts | grep -v '\.venv'
   ```
   Both must return nothing (they did on 2026-07-20). Also check `pyproject.toml`, `Makefile`, `.github/workflows/` for tool invocations by name before classifying anything as removable vs dev.
2. **Classify the remaining ~120 pins.** Mechanical aid: build a fresh venv from a candidate runtime list, run `pip check`, and boot the app (`uvicorn backend.v2.main:app`) — missing transitive pins surface immediately. Keep pins exact (this repo pins everything; keep that property).
3. **Create `backend/requirements-dev.txt`:**
   ```
   -r requirements.txt
   black==26.5.1
   flake8==7.3.0
   isort==8.0.1
   mongomock-motor==0.0.36
   pytest==9.0.3
   pytest-asyncio==1.3.0
   pytest-cov==7.1.0
   pytest-xdist==3.8.0
   ruff==0.6.9
   ```
   plus `mypy`, `import-linter`, `pip-audit` and their plugins if currently pinned in requirements.txt (check: `grep -in "mypy\|import-linter\|importlinter\|pip-audit\|pip_audit" backend/requirements.txt`).
4. **Update CI** (`.github/workflows/production.yml`): in both the `backend` (:107-108) and `backend-advisory` (:154-155) jobs, change `pip install -r requirements.txt` → `pip install -r requirements-dev.txt`; update both `cache-dependency-path` entries (:102, :149) to `backend/requirements-dev.txt`. Keep `pip-audit -r requirements.txt` (:115) pointed at the **runtime** file — auditing prod deps is the point — optionally add a second advisory audit of the dev file. Grep for other workflows: `grep -rn "requirements" .github/workflows/` (only production.yml referenced it on 2026-07-20).
5. **Dockerfile:** no change needed (`backend/Dockerfile:5-6` already installs only `requirements.txt`), but verify the image builds and boots (step below). Also grep `scripts/` and `Makefile`/docker-compose files for `requirements` in case local stacks install it: `grep -rn "requirements" scripts Makefile docker-compose*.yml`.

## Files to change

- `backend/requirements.txt` (shrink to runtime)
- `backend/requirements-dev.txt` (new)
- `.github/workflows/production.yml` (:102, :107-108, :149, :154-155)
- Possibly `scripts/local_test_stack.sh` / docs that mention `pip install -r requirements.txt` for dev setup (point dev instructions at `requirements-dev.txt`)

## Tests & verification

1. `docker build -f backend/Dockerfile backend/` succeeds.
2. Boot check: run the built image (or a clean venv with only the runtime file) against local Mongo; `GET /health` (backend on :8001 per `scripts/local_test_stack.sh`) returns OK, and app startup logs show no ImportError.
3. Fresh venv from `requirements-dev.txt`: `pytest v2/tests` passes (2,429 tests), `ruff check v2` clean, `lint-imports` clean.
4. CI green on the PR — the CI run itself is the authoritative "pytest still runs" check.
5. `pip check` clean in both venvs.

## Risks / rollback

- A "runtime" package imported lazily (inside a function) could pass boot but fail at request time. Mitigate: grep is repo-wide (catches lazy imports too); the six removals had zero hits anywhere.
- Wrong classification breaks CI, not prod (CI installs the superset). Prod risk is only from over-trimming runtime pins — the boot + smoke test covers it; the deploy pipeline's `smoke` job (production.yml:490) is the final guard.
- Rollback: single-PR revert restores the frozen file.

## PR checklist

- [x] Release note (per AGENTS.md `docs/release-notes/`)
- [x] TRACKER.md updated
- [x] Plan Status flipped to DONE
