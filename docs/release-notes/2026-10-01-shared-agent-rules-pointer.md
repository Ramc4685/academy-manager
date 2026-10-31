# Agents: point to the shared agent rules

PR: #1034

## What changed

- `AGENTS.md` now starts with one pointer line: `READ ~/Projects/agent-scripts/AGENTS.MD BEFORE ANYTHING (skip if missing).` The shared rules live in `Ramc4685/agent-scripts` (a fork of `steipete/agent-scripts`) and are also symlinked globally as `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`.
- Every repo rule below the pointer is unchanged. Where repo rules are stricter (pre-push gates, release notes, no force push, no amend), they win over the shared file.

## Deploy notes

- None. Documentation for coding agents only; no code, config, or migration change.

## Risk / rollback

- None for the app. Agents on machines without `~/Projects/agent-scripts` skip the pointer.
- Rollback: revert the PR.
