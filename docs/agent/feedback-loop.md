# Agent Feedback Loop

Use this file to keep multi-agent work from drifting.

The goal is a closed loop: discover, change, verify, record, hand off.

---

## Start Of Work

Run:

```bash
git status --short --branch
```

Then read:

1. `test_result.md`
2. Relevant active ledger under `docs/test-results/active/`, if one exists
3. Relevant ticket sheet, if `docs/tickets/` exists
4. Relevant ADR or policy docs
5. Existing code around the target files

Write down the current state before editing:

- What is already implemented?
- What is uncommitted?
- What is stale or unchecked?
- What is the next acceptance criterion?

---

## During Work

Keep changes small and traceable.

Repository changes must flow through pull requests. If a fix is needed after a
failed `main` run, create a new branch from `origin/main`, push that branch, and
open a PR instead of pushing another direct commit to `main`.

For ticketed work:

- Work one ticket or one coherent slice at a time.
- Keep ticket ID in branch, PR title, commit message, or handoff note when practical.
- Do not mark a ticket done until its acceptance criteria are verified.
- Do not open later wave tickets until the predecessor exit gate is met.

For non-ticketed bug fixes:

- Record the observed issue.
- Fix the narrow cause.
- Add regression coverage where practical.
- Note what was verified.

---

## Test Result Loop

Use `test_result.md` as the small index. Use per-task files under
`docs/test-results/active/` as the agent-to-agent source of truth.

Do not manually restore or edit large shared YAML status blocks in
`test_result.md`. Use the CLI so updates are append-only and task-scoped:

```bash
scripts/dev/test_result.py start "task title" --problem "What needs testing"
scripts/dev/test_result.py log task-title --agent main --status working --message "What changed"
scripts/dev/test_result.py verify task-title --message "pytest path/to/test.py -q passed"
scripts/dev/test_result.py close task-title
```

Before testing:

- Create or update the relevant active task ledger.
- Record whether code exists and whether it still needs retesting.
- Add files touched.
- Add clear scenarios for the testing agent.
- Add a log message explaining what changed.

After testing:

- Record pass/fail status in the task ledger.
- Record that retesting is complete only when the scenario was actually retested.
- Preserve failure details.
- Add new stuck tasks instead of burying failures in prose.

---

## Ticket Checklist Loop

When `docs/tickets/` exists:

- Check the active phase or wave before work starts.
- Update checkboxes only after acceptance is verified.
- Keep "done" separate from "files exist".
- If implementation exists but validation is missing, call it "implemented, unverified".
- If a ticket changes architecture, update the relevant ADR or policy doc.

Phase and wave exit gates require proof, not just created files.

---

## Handoff Note

If stopping before completion, leave a concise handoff in the final response or relevant status file:

```txt
Current state:
Changed files:
Verified:
Not verified:
Known failures:
Next step:
```

Do not leave future agents to infer state from a large diff.

---

## Learning Loop

When a repeated pattern or gotcha is discovered:

1. Update the focused `docs/agent/*` file if the guidance will help future agents.
2. Keep the note short and actionable.
3. Do not add one-off trivia.
4. Prefer commands and concrete rules over narrative.

Examples worth capturing:

- A test command that actually works.
- A required env var not obvious from code.
- A migration or deploy gotcha.
- A cross-persona auth rule.
- A flaky test workaround with a reason.

---

## Production-Scale Audit Handoff

When working on the production-scale local audit, keep the handoff tied to the
generated audit artifacts instead of prose memory.

Record these in the relevant `docs/test-results/active/` ledger before closing:

- Local data state: BLNO seed applied, synthetic scale rows applied, or why not.
- Auth state: `/tmp/academy-local-auth-env.sh` regenerated and `LOCAL_AUTH_E2E=1`
  used, or why not.
- Real-user result: exact Playwright command and pass/fail/skip counts.
- Gate result: `audit-readiness` result and `audit-gate` result.
- Artifact bundle: path under
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/`.
- Bug status: each confirmed `BUG-*` either verified, deferred, or blocked with
  reproduction evidence.

Do not close the ledger as complete if the aggregate gate is only
`READY_WITH_WARNINGS`. A complete audit needs `READY` and `CLEAN_PASS`; otherwise
leave a blocked handoff naming the warning/blocker and the command that produced
it.

---

## PR Failure Loop

When a PR check fails, do not guess from the GitHub UI summary.

1. Inspect the failed run:

   ```bash
   scripts/ci/pr_failure_feedback.py <actions-run-url-or-id>
   ```

2. Copy the failing job, failing step, command, and shortest useful log
   snippet into the relevant `docs/test-results/active/` ledger.
3. Add the missing local command to the relevant pre-push checklist when CI
   caught something the local loop did not.
4. Reproduce the first failed command locally before editing.
5. Fix the narrow cause, then rerun the failed command and the normal
   verification block for the touched area.
6. Only push after the local command that failed in CI is green.

For frontend changes, the CI-equivalent local block is:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm audit --audit-level=high
pnpm typecheck
pnpm lint
pnpm build
```

If `pnpm audit --audit-level=high` fails, treat it as blocking. Prefer a
targeted dependency upgrade or package-manager override over bypassing the
audit gate.
