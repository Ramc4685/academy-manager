# Testing and Verification Rules

Every change needs verification.

Never claim done without evidence.

---

## Default Commands

Backend:

```bash
cd backend
source .venv/bin/activate
pytest
```

Frontend:

```bash
cd frontend
pnpm typecheck
pnpm build
```

Container smoke:

```bash
docker compose up --build
curl http://127.0.0.1:8001/api/health
```

v2 backend:

```bash
cd backend
pytest v2/tests
```

---

## Verification Strategy

- Run focused tests first.
- Run broader checks after focused behavior passes.
- Run frontend build after route, bundling, or environment changes.
- Run backend tests after API, auth, database, billing, or scheduler changes.
- Run browser checks for UI changes.
- Run smoke tests after deployment or CORS/auth changes.
- State skipped checks and why they were skipped.

---

## Bug Fix Rules

- Reproduce first when possible.
- Identify the failing path.
- Find the root cause.
- Avoid symptom-only patches.
- Add regression coverage when practical.
- Record the failure mode in the final response or `test_result.md` when relevant.

---

## Testing Agent Protocol

This repo uses `test_result.md` as the shared ledger between main and testing agents.

Before calling a testing agent:

1. Update `test_result.md`.
2. Mark changed tasks with `needs_retesting: true`.
3. Add implementation details and files touched.
4. Update `test_plan.current_focus`.
5. Add an `agent_communication` note with exact scenarios to test.

After testing:

1. Record pass/fail status.
2. Preserve testing-agent context.
3. Keep stuck tasks visible.
4. Do not reset `stuck_count` until a retest confirms the fix.

---

## UI Verification

For UI changes:

- Use browser verification.
- Verify the affected page.
- Verify the golden path.
- Verify mobile behavior for coach/parent flows.
- Capture screenshots when the visual result matters.

---

## Final Verification Report

Final response must state:

1. Commands run.
2. Results.
3. Manual checks completed.
4. Checks not run.
5. Why skipped checks were skipped.

Do not fake verification.
