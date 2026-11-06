# AI Phase 3 D2: read-only report tool registry

## What changed

- New `backend/v2/contexts/ai/application/tools.py`: a registry of thirteen read-only tools, one per admin report (dashboard, session economics, projected income, enrollment funnel, attendance trends, coach utilization, refunds, revenue by category, deposit slip, money owed by age, inquiry conversion, attendance risk, families lost).
- Each tool validates its arguments, applies the same owner and family-money gates as the report route, runs the existing use case inside the caller's tenant scope and returns the route's response model as JSON, cut to 12,000 characters.
- The registry renders in the Anthropic tool-use shape for the "ask the academy" slice (D3). Wiring lives in the new `backend/v2/composition/ai_tools.py`.

## Deploy notes

- None. Nothing calls the registry yet: no route, no model call, no migration, no setting.

## Risk / rollback

- No runtime path reaches the new code, so the risk is nil until D3 wires it. Rollback is a revert of this PR.

PR: #1156
