# api-contract-check

PR: #1144

## What changed
The frontend and backend API shapes are now checked against each other in CI. The backend's OpenAPI description is committed as `frontend/lib/api/openapi.snapshot.json`, with frontend types generated from it. A backend structural test fails when the live API differs from the snapshot. It always renders with the platform, owner and student routes mounted, so the result does not depend on a deployment's feature flags, and the existing frontend drift step now fails instead of silently skipping. A new compile-time contract pins 18 billing endpoints the parent and admin money screens read, so a renamed or retyped field fails typecheck instead of breaking a page. The collections view now declares a paused family's `enrollment_id` and `student_name` as always present, which they already were.

## Deploy notes
None. No migration and no env vars. The only runtime-adjacent change is the tighter collections response model, which matches what the endpoint already returns.

## Risk / rollback
Any pull request that changes an API shape must now also refresh the snapshot and generated types, or CI fails with the exact command to run. Roll back by reverting the PR.
