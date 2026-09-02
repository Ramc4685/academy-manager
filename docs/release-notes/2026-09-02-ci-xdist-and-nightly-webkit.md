# ci-xdist-and-nightly-webkit

PR: #626

## What changed
- The backend test job now runs `pytest -n auto`. The ~3,600-test v2 suite
  ran single-process in CI (about 174 seconds) even though pytest-xdist was
  already a dev dependency; in parallel it takes about 60 seconds and
  pytest-cov still combines worker coverage against the 86% floor.
- The WebKit mobile Playwright project moved out of `production.yml` into a
  new `nightly-e2e.yml`. It was the longest job on the pre-deploy critical
  path (about 9 minutes versus about 6 for Chromium mobile). It still runs
  daily at 09:15 UTC, on manual dispatch, and on PRs that touch
  `frontend/e2e/**` or the Playwright config.
- `CI Gate` no longer lists the WebKit job in `needs`. `docs/ci-cd.md` is
  updated to describe the new split.

## Deploy notes
No application code changes; nothing to deploy. The first scheduled
`Nightly E2E` run happens the morning after merge. A WebKit failure there is
an email from GitHub Actions, not a deploy blocker, and should be triaged
like any other e2e regression.

## Risk / rollback
Low. A WebKit-only regression can now merge and deploy before the nightly
run catches it; the last 30 days of runs show no WebKit-only failures, and
Chromium mobile still runs on every PR. Rollback is reverting this PR, which
restores the WebKit job to the gate and the single-process pytest command.
