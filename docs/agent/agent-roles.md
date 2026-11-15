# Agent roles and model routing

How the agents building this repo are organised. The lead follows this table, and uses judgement only where
the table doesn't decide. Agent definitions live in `.claude/agents/`, each with its model pinned.

## Roles

| Role | Model, effort | Runs as | Does | Never |
|---|---|---|---|---|
| Lead | Opus | the coordinating session; a new session each day or milestone, started from `docs/agent/lead-handoff.md` | owns the roadmap, writes each brief, routes each task to a role, merges reviewed work, reports to the owner | writes or edits product code |
| Planner | Fable, high | `planner` subagent | called only when the lead cannot write a confident brief, or before building anything in the risk areas below; one call per question | edits files, assumes a product decision |
| Builder | Opus, medium | its OWN CHIP SESSION in its own worktree for any feature or fix round, kept through review fixes; the `builder` subagent only for a fix of a few lines | builds one slice end to end; runs the full suite after its last merge before reporting ready; reports once, at the end | merges to the default branch, touches another chip's files |
| Reviewer | Opus, medium | `reviewer` subagent | reviews every change before merge | edits code |
| Risk reviewer | Fable, high | `risk-reviewer` subagent | one pass per risky branch (rule 1); the lead verifies fixes by reading the diff | edits code |
| Mechanical | Haiku, low | `mechanical` subagent | seeds, fixtures, status tables, docs sync, lint and format, regenerated files | design decisions, domain logic |

**Chip or subagent.** A feature, or a fix round on a feature branch, is a chip session: it keeps its context
through review fixes, which a subagent cannot. Reviews, planning, chores and fixes of a few lines are subagents.
At most 2 chips in flight (16 GB Mac, one full gate at a time). A chip is archived as soon as its branch merges, with its worktree removed.

## Routing rules

1. A change touching any of these gets the risk reviewer as well as the reviewer: `backend/v2/contexts/billing/`, `backend/v2/shared/tenancy/`, `backend/v2/shared/auth/`, `load_auth_claims.py`, the Stripe webhook route and its dedup, `frontend/app/api/v2/[...path]/route.ts`, CORS in `backend/v2/main.py`, `docs/security-matrix.md`, any
   migration, any public or anonymous route, money or PII handling, or files from more than one chip.
2. Work that is only seeds, fixtures, docs, status tables, lint or regenerated files goes to mechanical.
3. Everything else that changes code goes to a builder, then the reviewer.
4. A builder that fails the same gate twice goes back to the lead, which re-scopes the brief rather than retrying.

## Briefs (lead to builder)

Every brief states: the goal, the files and module it owns, what is out of scope, the contracts and migrations
involved, what done looks like (tests, screenshot), and what was already ruled out. Builders return a short
report and write longer output to their chip's notes file, not to the lead.

## Gating

Builders push only their own `<type>/<name>` branch (a Conventional Commits type: `feat/`, `fix/`, `docs/`,
`chore/`, `refactor/`, `test/`, `perf/`, `build/`, `ci/`, `style/`) and open a pull request; CI runs the full gate.
Pushing or merging to `main` stays with the owner; the GitHub ruleset enforces it (required CI Gate and Release
Notes Gate). The global guard mod (`~/.claude/mods/guard`) blocks force pushes and destructive git commands.

No AI attribution anywhere: branch names, commit messages and PR bodies never mention Claude, Codex or AI, and
carry no `Co-Authored-By` or "Generated with" lines. In this repo the pre-push hook runs
`scripts/dev/pre-push-checks.sh` (about 40 minutes), so run the push in the background. A PR also needs a release
note (`AGENTS.md`, Release Notes) and a `/code-review` pass before it opens.

## Capacity

A 16 GB Mac: one full gate at a time, each against its own mongod (`AGENTS.md`, Gotchas). Chips stop their servers
when their gate finishes.

## Handoff file

`docs/agent/lead-handoff.md` is git-ignored: this repo is public and the handoff holds owner decisions and
production state. Keep it in the main checkout and never commit it.

## Workflows

`.claude/workflows/fix-issue-batch.js` runs a batch of small bug issues end to end (diagnose, plan lanes, fix,
review, ship). Its agents pass `model` per call, and its security lens uses `risk-reviewer`. Use it for many small
issues at once; a feature still goes to a chip.

## Never

- Delegate code work to an unpinned agent (`general-purpose`, or any agent file with `model: inherit`): its model
  follows the lead's, which can change mid-run.
- Set `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`: it overrides every pinned model above.
