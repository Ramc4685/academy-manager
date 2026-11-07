# playwright-deps-retry

PR: #1159

## What changed
- CI only. The Playwright e2e jobs (Chromium shards, Chromium Desktop, Real Auth, and the nightly WebKit and Chromium jobs) now install Playwright's apt system packages through `scripts/ci/playwright_install_deps.sh`. Each attempt gets 150 seconds. If the first one is slow or fails, the script stops the stuck `apt-get`, finishes any interrupted dpkg run, switches from `azure.archive.ubuntu.com` to `archive.ubuntu.com` and tries once more. Before, a throttled Azure mirror (~35 kB/s on PR #1155) could spend ~9.5 minutes of the 12-minute Chromium job on font downloads and get the job cancelled.

## Deploy notes
No app change, no migration. Nothing to deploy.

## Risk / rollback
Low. In the worst case (both attempts slow) the step fails after about 5.5 minutes instead of hanging, so the job still goes red, just sooner and with a clear `::error::`. Roll back by reverting the PR.
