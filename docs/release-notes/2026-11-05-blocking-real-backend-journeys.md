# blocking-real-backend-journeys

PR: #1147

## What changed
CI-only. The real-backend journeys step in the `Frontend E2E Real Auth` job (added in #1145) is now blocking. A failing journey fails the job and CI Gate. Before, the step was `continue-on-error`. The owner agreed to make it required once it had passed in CI twice in a row. It passed on #1145's last two heads.

## Deploy notes
No app code changed, and there is nothing to deploy.

## Risk / rollback
If a flaky journey starts blocking unrelated PRs, add `continue-on-error: true` back to the journeys step. To roll back fully, revert this PR.
