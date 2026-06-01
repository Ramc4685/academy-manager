# Test Result Ledgers

Use this directory for task-specific testing handoffs.

`test_result.md` is only an index. Keep detailed status, verification evidence,
skipped checks, and handoff notes in per-task files under `active/`.

## Commands

```bash
scripts/dev/test_result.py start "task title" --problem "What needs to be verified"
scripts/dev/test_result.py log task-title --agent main --status working --message "What changed"
scripts/dev/test_result.py verify task-title --message "pytest path/to/test.py -q passed"
scripts/dev/test_result.py close task-title
```

## Rules

- Do not restore the old global YAML ledger in `test_result.md`.
- Keep one coherent task or defect bundle per active file.
- Archive completed ledgers with `scripts/dev/test_result.py close`.
- Promote reusable lessons to `docs/agent/testing-verification.md` or
  `docs/agent/feedback-loop.md`.
- Keep one-off command output and branch-specific history in the task ledger.

## Archive

The pre-split global ledger is preserved at
`docs/test-results/archive/2026-06-01-pre-split-test-result.md`.
