# Tickets

Architecture frozen at [/Users/ramc/.claude/plans/write-a-detailed-plan-curried-trinket.md](../../../../../.claude/plans/write-a-detailed-plan-curried-trinket.md) (approved 2026-05-16).

Tickets are written **one wave at a time**. The next wave's tickets are authored only after the current wave's exit gate is met. This is intentional — see plan §"Final Architecture Rules" #3.

## Current sheets

| Sheet | Status | Tickets | Estimate |
|---|---|---|---|
| [Phase 0 — Guardrails](phase-0-guardrails.md) | Code landed | P0-01 … P0-22 (22) | ~1 week |
| [Wave 1A — Coach Today](wave-1a-coach-today.md) | Code landed | W1A-01 … W1A-21 (21) | ~2 weeks |
| [Wave 1B — Coach Offline Writes](wave-1b-coach-offline-writes.md) | Code landed | W1B-01 … W1B-10 (10) | ~1.5 weeks |
| [Wave 2 — Parent Checkout](wave-2-parent-checkout.md) | Code landed | W2-01 … W2-22 (22) | ~3 weeks |
| [Wave 3 — Admin Control Plane](wave-3-admin-control-plane.md) | Code landed | W3-01 … W3-18 (18) | ~3–4 weeks |
| [Wave 4 — Decommission](wave-4-decommission.md) | Code + runbook landed | W4-01 … W4-12 (12) | ~1 week + 30d soak |
| [Post-MVP Admin Multi-Role Users](post-mvp-admin-multi-role-backlog.md) | Backlog | AMR-01 … AMR-06 (6) | ~3–4 days |

"Code landed" means the file scaffolding, application logic, tests, migrations, and runbooks are committed. Production cutover for each wave remains gated by its exit checklist and the soak windows defined in [the plan](/.claude/plans/write-a-detailed-plan-curried-trinket.md).

## Conventions

- IDs: `<Phase>-NN`. Sortable, unique.
- Estimates: ideal hours. Wall-clock includes review, CI, and soak time.
- Each ticket: Type, Depends on, Estimate, Description, Acceptance.
- Each sheet ends with an exit checklist that maps to the plan's exit gates.
- Dependencies cross sheets via ticket ID (e.g., W1A-01 depends on P0-17).
- A wave does **not** open until its predecessor's exit checklist is complete.

## Workflow

1. Pick the topmost unblocked ticket in the current sheet.
2. Branch: `<id>-<short-slug>` (e.g., `p0-11-backend-skeleton`).
3. PR title includes the ID.
4. Merge requires the acceptance criteria checked.
5. On wave exit checklist completion: retro, then open the next wave's sheet.
