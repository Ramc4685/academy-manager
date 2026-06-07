# AGENTS cross-agent automation note

## Current State

Status: active

## Problem

Document that AGENTS.md remains canonical while Claude Code automations live under .claude for Claude-specific enforcement

## Changed Files

- None recorded yet.

## Log

- 2026-06-07T15:15:00 main/NA: Task ledger created.
- 2026-06-07T15:15:38 main/working: Added a short AGENTS.md note clarifying that .claude automations support AGENTS.md and that AGENTS.md remains canonical for all agents.
## Verification

- No verification recorded yet.
- 2026-06-07T15:16:08: Docs verification: sed -n '1,32p' AGENTS.md confirmed placement and wording; git diff --check -- AGENTS.md passed; scoped Python check confirmed inserted note is present and ASCII. Whole-file ASCII check was skipped after it failed on pre-existing non-ASCII punctuation elsewhere in AGENTS.md.
## Reusable Lessons

- None recorded yet.
