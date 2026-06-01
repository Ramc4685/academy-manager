# Test Result Index

This file is intentionally small to avoid merge conflicts.
Use the per-task ledgers under `docs/test-results/active/` for current handoffs.

## Active Test Result Files

No active test result files.

## Required Workflow

- Start a task: `scripts/dev/test_result.py start "task title" --problem "..."`
- Add status: `scripts/dev/test_result.py log <slug> --agent main --status working --message "..."`
- Add verification: `scripts/dev/test_result.py verify <slug> --message "..."`
- Close a task: `scripts/dev/test_result.py close <slug>`
- Do not manually edit large shared status blocks in this file.

## Learning Loop

- Keep task-specific evidence in the relevant active ledger.
- Promote reusable lessons to `docs/agent/testing-verification.md` or `docs/agent/feedback-loop.md`.
- Archive completed task ledgers with the `close` command.
