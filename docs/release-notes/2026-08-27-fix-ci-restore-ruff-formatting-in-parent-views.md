# fix-ci-restore-ruff-formatting-in-parent-views

PR: #463

## What changed
Restored `ruff format` compliance in `backend/v2/interfaces/parent/views.py`.
The merges of #375 (Messages/Calendar) and #380 (parent profile completion)
each landed cleanly on their own, but together left the
`# --- Self-service profile (issue #380) ---` section comment butted directly
against the end of `ParentMarkMessageReadResponse` with no blank-line
separation. That turned `main` red at the Backend Lint → "Ruff format check v2"
step (run 33120556090), which also blocked every downstream job including the
production deploy.

The change is exactly the two blank lines `ruff format` inserts — no code,
schema, or behaviour is touched.

## Deploy notes
none — formatting-only change. No migrations, env vars, or manual steps.
Merging this unblocks the production pipeline on `main`.

## Risk / rollback
No runtime risk: the diff is whitespace between two top-level definitions and
does not alter any Python semantics. Rollback is a single-file revert, which
would simply re-red the Backend Lint job.
