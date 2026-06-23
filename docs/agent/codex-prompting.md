# Codex Prompting Guidance

Use this file when the user asks an agent to draft, improve, or package a
prompt for Codex. The goal is to turn user intent into an auditable operating
contract, not just a longer task description.

This guidance distills the local Codex docs the user provided:

- Goals are persistent, thread-scoped objectives with evidence-based completion.
- Strong prompts name the outcome, verification surface, constraints, boundaries,
  iteration policy, and blocked stop condition.
- Codex performs best when prompts preserve autonomy, require codebase
  exploration, encourage focused verification, and avoid stopping at a plan.

---

## Choose Prompt Or Goal

Use a normal prompt when the work is a single bounded action:

- Explain a file or command result.
- Make a small edit.
- Draft a short plan.
- Review a specific diff.

Use a `/goal` when the work has a clear finish line but the path may require
iteration:

- Multi-step feature work.
- Bug hunts where reproduction is uncertain.
- Performance or flaky-test work.
- Research or audit work that must separate confirmed facts from uncertainty.
- Any task where the user would otherwise keep saying "continue" or "try the
  next likely fix."

For large implementation work, produce both:

1. A compact `/goal` completion contract.
2. A longer execution brief with files, context, slices, and verification.

---

## Strong Goal Template

```text
/goal <desired end state>, verified by <specific tests, browser checks, reports, or artifacts>, while preserving <constraints>. Use <allowed repo areas, docs, tools, or boundaries>. Work in <small slices / TDD-backed iterations / evidence-backed passes>. After each slice, record <what changed and what evidence was gathered>. If blocked or no safe path remains, stop with <attempted paths, evidence, blocker, and input needed>.
```

A goal is complete only when the evidence matches the objective. Budget limits,
partial progress, or likely correctness do not count as completion.

---

## Execution Brief Structure

When drafting an implementation prompt, include these sections in this order:

1. **Objective**: One sentence describing the user-visible outcome.
2. **Required reading**: `AGENTS.md`, repo docs, ticket/spec files, active ledger,
   and any attached or referenced source material.
3. **Current issue**: Concrete observed behavior, including exact routes, errors,
   commands, or screenshots if available.
4. **Relevant files**: Known entry points, tests, API clients, routes, components,
   and supporting docs.
5. **Architecture constraints**: v2/DDD/BFF boundaries, legacy exclusions, tenant
   isolation, billing safety, auth rules, or other project non-negotiables.
6. **Implementation slices**: Ordered smallest coherent changes, with the first
   checkpoint explicit.
7. **Tests and verification**: Commands, browser checks, regression tests, and
   ledger updates expected before claiming done.
8. **Blocked behavior**: What to do if a slice is unsafe, too broad, or cannot be
   verified in the current environment.

Prefer concrete nouns over vague instructions. Name the page, route, command,
ledger, and acceptance evidence whenever known.

---

## Project-Specific Prompt Rules

- Start from `AGENTS.md` and the focused `docs/agent/*` file for the task.
- Require the repo feedback loop: create or update the active ledger with
  `scripts/dev/test_result.py log/verify`.
- Tell Codex to inspect existing code before editing.
- Ask for a concise implementation plan before edits on non-trivial work, mapped
  to the spec or ticket acceptance criteria.
- Preserve the current architecture: backend truth in v2 application/domain/BFF
  layers; frontend remains presentation-focused.
- For SaaS work, keep legacy `/api/*` out of scope unless the user explicitly
  asks for a legacy fix.
- For billing work, repeat the billing safety rules instead of relying on memory.
- For frontend work, require browser/mobile verification when UI behavior changes.
- For production-impacting work, explicitly forbid deploys, destructive database
  operations, and real email unless the user approves.
- If a workflow may be broader than the prompt can safely cover, instruct Codex
  to implement the smallest safe slice and document the follow-up blocker.

---

## Useful Wording

Use this wording when a task should continue through implementation:

```text
Do not stop after planning. After the plan, implement the smallest coherent
slice unless you find a concrete blocker. Verify before claiming done and record
exact commands/results in the active ledger.
```

Use this wording when optional scope could become risky:

```text
Inspect the existing workflow first. If this fits existing services and
authorization boundaries, implement the smallest safe route/action. If it needs a
larger architecture change, document the blocker and recommended follow-up rather
than forcing a risky patch.
```

Use this wording for investigations:

```text
Investigate the root cause rather than hiding the symptom. End with confirmed
findings, changed files, verification performed, and any remaining uncertainty.
```

---

## Prompt Quality Checklist

Before handing the prompt to Codex, confirm it answers:

- What exact end state should be true?
- What evidence proves it?
- What must not change?
- Which files/docs/specs should be read first?
- Which work is explicitly out of scope?
- What should Codex do if verification cannot run?
- Where should progress and skipped checks be recorded?

If any answer is missing, add it before using the prompt.
