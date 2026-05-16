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
2. Relevant ticket sheet, if `docs/tickets/` exists
3. Relevant ADR or policy docs
4. Existing code around the target files

Write down the current state before editing:

- What is already implemented?
- What is uncommitted?
- What is stale or unchecked?
- What is the next acceptance criterion?

---

## During Work

Keep changes small and traceable.

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

## `test_result.md` Loop

Use `test_result.md` as the agent-to-agent source of truth.

Before testing:

- Add or update the task entry.
- Set `implemented: true` when code exists.
- Set `working: "NA"` until tested.
- Set `needs_retesting: true`.
- Add files touched.
- Add clear scenarios in `test_plan.current_focus`.
- Add an `agent_communication` message.

After testing:

- Set `working: true` or `false`.
- Set `needs_retesting: false` only when the scenario was actually retested.
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
