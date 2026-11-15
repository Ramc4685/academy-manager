# agent-guidance-cleanup

PR: #1165

## What changed
- Agent setup: a lead session plus five agents with pinned models (planner, builder, reviewer, risk-reviewer, mechanical) replace the old security and boundary reviewer agents. Routing, briefs and gating live in `docs/agent/agent-roles.md`.
- AGENTS.md and `docs/agent/*` corrected for Next.js 16, the current test count and stack; the verification ledger is now optional; nine recurring gotchas promoted from session notes.
- Removed the unused `academy-verification` and `v2-persona-slice` skills.
- `fix-issue-batch` workflow is now tracked and hardened: issue text is treated as untrusted data, lane names and commit hashes are validated before use, branch reuse only considers existing local branches, the security review runs on the pinned risk-reviewer, and PRs carry no AI attribution.
- README stack, layout and deploy pipeline now match the code; EGM drift reports added for the repo root and `docs/agent`.

## Deploy notes
Docs and agent tooling only. No app, migration, or data change.

## Risk / rollback
Low. Nothing in the running app changes. Roll back by reverting the PR.
