# security-hardening

PR: #1085

## What changed
Dependabot keeps one PR per ecosystem and now also groups security updates into one PR each for pip and npm. It also watches the backend and frontend Dockerfiles monthly, labels its PRs, and runs Mondays at 06:00 Central. The Release Notes Gate is skipped on PRs opened by Dependabot, so grouped dependency PRs no longer need to be consolidated by hand. `pnpm/action-setup` is pinned to a commit SHA. Adds `SECURITY.md` and `CODEOWNERS`.

## Deploy notes
None. CI and repository configuration only; no app code or migrations.

## Risk / rollback
Low. If Dependabot reports a config error or the gate skip misbehaves, revert the PR.
