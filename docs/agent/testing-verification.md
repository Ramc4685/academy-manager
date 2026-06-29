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
pnpm audit --audit-level=high
pnpm typecheck
pnpm lint
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
- Run the same audit and install commands used by CI when dependency files
  change.
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
- Record the failure mode in the final response or relevant `docs/test-results/active/`
  ledger when relevant.

---

## Testing Agent Protocol

This repo uses `test_result.md` as a small index and `docs/test-results/active/`
files as the shared ledger between main and testing agents.

Use the CLI; do not manually edit large shared status blocks in `test_result.md`.

Before calling a testing agent:

1. Create or update the task ledger with `scripts/dev/test_result.py`.
2. Mark changed tasks as needing retest in the task ledger.
3. Add implementation details and files touched.
4. Add exact scenarios to test.
5. Keep `test_result.md` as the generated index only.

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

## Production-Scale Local Audit

Use this when the task asks for broad release confidence, production-like local
data, real-user route inventory, or "every user-facing feature/route/control"
verification.

The audit is local-only. It uses sanitized BLNO SaaS staging data, the local
Mongo/Firebase emulator stack, and Playwright real-auth tests. Do not use
production data or production services for this audit.

Required setup:

```bash
scripts/dev/saas_staging.sh blno-seed
scripts/dev/saas_staging.sh scale --apply --parents 250 --students-per-parent 2
scripts/dev/saas_staging.sh local-auth-env > /tmp/academy-local-auth-env.sh
set -a; . /tmp/academy-local-auth-env.sh; set +a
```

Required clean-pass checks:

```bash
LOCAL_AUTH_E2E=1 scripts/dev/saas_staging.sh audit-readiness
cd frontend
LOCAL_AUTH_E2E=1 pnpm exec playwright test -c playwright.local-auth.config.ts
cd ..
LOCAL_AUTH_E2E=1 scripts/dev/saas_staging.sh audit-gate
LOCAL_AUTH_E2E=1 scripts/dev/saas_staging.sh audit-artifacts
```

Expected final state:

- `audit-readiness` reports `READY`.
- `audit-gate` reports `CLEAN_PASS`.
- Playwright reports all local-auth inventory tests passed, with zero failed
  and zero skipped tests.
- Evidence is written under
  `/tmp/academy-manager-local/evidence/20260628-production-scale-audit/`.
- The bug log in `docs/qa/*production-scale-local-bug-log.md` records every
  confirmed defect with reproduction evidence, root cause, fix, regression test,
  and rerun result.
- The manifest in `docs/qa/*production-scale-local-inventory-manifest.json`
  names the user-facing routes, workflows, buttons, inputs, modals, states,
  risk edges, and acceptance criteria covered by the audit.

If `audit-static-gaps`, `audit-acceptance`, `audit-control-evidence`, or
`audit-gate` reports warnings or blockers, do not call the audit clean. Either
fix the manifest/scanner/test/data issue and rerun the full local-auth
Playwright inventory, or leave a blocked handoff with the exact failing command
and artifact path.

Safety rules:

- `scale --apply` mutates local staging data only. It is allowed after explicit
  local approval; cleanup or reset still needs explicit approval because it
  deletes local Mongo/emulator data.
- `local-auth-env` may write local test credentials to `/tmp`; do not paste
  passwords or tokens into final responses, PR descriptions, or docs.
- `saas_staging.sh smoke` can rewrite the generic staging credentials file.
  Regenerate `/tmp/academy-local-auth-env.sh` before rerunning Playwright.
- Use `scripts/dev/validate_scale_seed_safety.py` before changing scale seed
  shape. It must not touch Mongo.

---

## Final Verification Report

Final response must state:

1. Commands run.
2. Results.
3. Manual checks completed.
4. Checks not run.
5. Why skipped checks were skipped.

Do not fake verification.
