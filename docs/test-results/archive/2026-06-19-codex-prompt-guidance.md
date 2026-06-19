# codex prompt guidance

## Current State

Status: active

## Problem

Save reusable Codex prompt and goal-writing guidance in repo docs so future prompt requests follow the documented structure.

## Changed Files

- None recorded yet.

## Log

- 2026-06-19T08:22:17 main/NA: Task ledger created.
- 2026-06-19T08:23:10 main/working: Added docs/agent/codex-prompting.md with Codex goal/prompt structure distilled from the provided docs, and routed prompt/goal drafting tasks to it from AGENTS.md and docs/agent/README.md.
## Verification

- No verification recorded yet.
- 2026-06-19T08:23:45: Docs verification passed: git diff --check -- AGENTS.md docs/agent/README.md test_result.md produced no output; awk trailing-whitespace scan for docs/agent/codex-prompting.md and the active ledger produced no output; rg confirmed AGENTS.md and docs/agent/README.md route prompt/goal work to docs/agent/codex-prompting.md and the guide contains the goal/execution brief sections.
## Reusable Lessons

- None recorded yet.
