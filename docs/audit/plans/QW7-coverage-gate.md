# QW7 — Widen CI coverage gate from v2/shared to v2
Status: DONE (PR #310, 2026-07-20)
Size: XS · Depends on: none · Tracker: ../TRACKER.md

## Problem
The coverage gate only measures `v2/shared`; contexts, composition, and interfaces (the bulk of the backend, including all money paths) have zero enforced coverage floor.

## Current behavior (verified)
- `.github/workflows/production.yml` (v2 backend tests step, ~line 128):
  `pytest v2/tests --override-ini="testpaths=v2/tests" --cov=v2/shared --cov-report=term-missing --cov-fail-under=70`
- 2,429 tests pass in ~84s (audit), so widening measurement is cheap; only the floor number is unknown.

## Implementation steps
1. Measure first, locally:
   `cd backend && pytest v2/tests --override-ini="testpaths=v2/tests" --cov=v2 --cov-report=term | tail -5`
   Record TOTAL %.
2. Edit the workflow step: `--cov=v2/shared` → `--cov=v2`, and set `--cov-fail-under=<floor>` where floor = measured TOTAL rounded **down** to the nearest whole percent, minus 1 (buffer for platform variance). Example: measured 78.4% → floor 77.
3. Add a one-line comment above the step: `# Ratchet: raise fail-under toward measured coverage whenever it grows; never lower without a tracker note.`
4. If measured total is dominated by generated/trivial files, optionally add `--cov-report=term-missing:skip-covered` for readable CI logs (no behavior change).

## Verification
- Local command in step 1 passes with the new floor.
- Push branch; the "v2 backend tests" CI job passes with the widened `--cov=v2`.
- Deliberately sanity-check the gate bites: run locally with `--cov-fail-under=99` → fails.

## Risks / rollback
- If local and CI coverage differ (test skips on macOS vs linux), CI could fail at the chosen floor — the −1 buffer covers this; if it still trips, lower the floor to the CI-measured value in a follow-up commit. Rollback = revert the two flags.

## PR checklist
- [ ] Release note if backend/ or frontend/ changed (per AGENTS.md)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
