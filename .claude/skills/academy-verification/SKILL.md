---
name: academy-verification
description: This skill should be used when working in academy-manager and the user asks to "verify", "run checks", "finish the task", "prepare handoff", "call a testing agent", "update test_result", or when code changes require repo-specific verification evidence.
version: 0.1.0
---

# Academy Verification

Use this skill to run the academy-manager verification loop consistently.

## Workflow

1. Inspect current state before changing or reporting:

   ```bash
   git status --short --branch
   sed -n '1,160p' test_result.md
   ls docs/test-results/active
   ```

2. Select or create the active ledger:

   ```bash
   scripts/dev/test_result.py start "task title" --problem "What needs to be verified"
   ```

   Reuse an existing active ledger when it already matches the task. Avoid manually restoring the old global YAML ledger in `test_result.md`.

3. Record implementation state before handing work to another agent or before final verification:

   ```bash
   scripts/dev/test_result.py log task-title --agent main --status working --message "What changed"
   ```

4. Choose focused verification from touched areas:

   Backend v2:

   ```bash
   cd backend
   source .venv/bin/activate
   pytest v2/tests/path_or_file.py -q
   ruff check v2
   ruff format --check v2
   ```

   Frontend:

   ```bash
   cd frontend
   pnpm typecheck
   pnpm lint
   pnpm build
   ```

   CI-equivalent frontend dependency check when dependency files change:

   ```bash
   cd frontend
   pnpm install --frozen-lockfile
   pnpm audit --audit-level=high
   ```

   Browser/UI changes:

   ```bash
   scripts/local_test_stack.sh all
   ```

   Then verify the affected persona flow in a browser, including mobile behavior for coach and parent flows.

5. Record verification evidence exactly:

   ```bash
   scripts/dev/test_result.py verify task-title --message "Command/result or skipped check reason"
   ```

6. Finish with a concise report containing:

   - What changed.
   - Files changed.
   - Verification performed with command results.
   - Remaining risks or skipped checks.
   - Next recommended step, when useful.

## Guardrails

- Activate `backend/.venv` before running Ruff manually; system Ruff may differ from CI.
- Run focused checks first, then broader checks when the blast radius warrants it.
- Do not claim a check passed unless the command actually ran and passed.
- Record skipped checks with a reason, not silence.
- Keep unrelated dirty files out of summaries except to identify them as pre-existing.
