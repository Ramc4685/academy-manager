# AGENTS.md

Agent guidance for `academy-manager`.

Applies to Claude Code, Codex, and any AI coding agent.

This file is the root router. Detailed rules live in `docs/agent/`.

---

## Read First

Before coding, read:

1. `README.md`
2. `DEPLOYMENT.md`
3. `test_result.md`
4. The focused rule file for the task.

If the branch contains `docs/tickets/`, also read:

1. `docs/tickets/README.md`
2. The current phase or wave ticket sheet.
3. Any ADR or policy doc referenced by the ticket.

Do not treat `.claude/worktrees/*` as canonical project source unless the user explicitly asks about that worktree.

---

## Task Routing

| Task type | Read |
| --- | --- |
| Architecture / DDD / BFF / migration plan | `docs/agent/architecture-rules.md` |
| Backend / API / Mongo / auth / payments | `docs/agent/backend-api-rules.md` |
| Frontend / React / UI / PWA | `docs/agent/frontend-rules.md` |
| Testing / verification / bug fixing | `docs/agent/testing-verification.md` |
| Status handoff / agent loop / ticket updates | `docs/agent/feedback-loop.md` |

---

## Project Snapshot

Current production app:

- Backend: FastAPI, Motor/PyMongo, MongoDB, Firebase Admin SDK, Stripe, Resend, APScheduler.
- Frontend: Next.js 15 App Router, React 19, Tailwind, Firebase Web SDK, PWA.
- Auth: Firebase Authentication in production; legacy password auth can be disabled with `FIREBASE_AUTH_ENABLED=true`.
- Deployment: Fly.io backend app `courtmastr-academy-api`; Cloudflare Worker frontend `academy-next`.
- Local services: backend `http://127.0.0.1:8001/api`, frontend `http://localhost:3001`, MongoDB `mongodb://127.0.0.1:27017`.

Migration direction:

- Keep legacy `/api/*` stable.
- Add v2 capabilities incrementally behind flags and edge routing.
- v2 backend uses BFF + DDD boundaries under `backend/v2/` when present.
- Frontend uses the canonical Next.js app under `frontend/`.
- Do not big-bang rewrite.

SaaS direction:

- SaaS mode is v2-only.
- Legacy `/api/*` routes are not part of SaaS mode and must not be patched for SaaS readiness.
- New SaaS workflows must use `backend/v2/` BFF + DDD boundaries.
- Do not use `default_academy_id` in SaaS request paths.
- Tenant identity must be membership-based: global `users`, `academy_memberships`, and platform roles.
- Tenant resolution must be explicit: subdomain, custom domain, or approved internal header; never infer tenant from user alone.
- Every tenant-owned read/write must use request-scoped tenant context and tenant isolation tests.
- There is no production SaaS data to migrate; build clean v2 SaaS bootstrap instead of legacy backfill.
- See `docs/requirements/2026-05-21-saas-data-model-architecture-assessment.md` and `docs/plans/2026-05-21-saas-v2-parallel-execution-plan.md`.

---

## Golden Rules

- Read existing code before editing.
- Make small, surgical changes.
- Preserve working behavior.
- Keep legacy bug fixes isolated from v2 migration work.
- Follow DDD boundaries in `backend/v2`.
- Keep BFF APIs persona-shaped, not generic CRUD.
- Keep frontend presentation-focused; business truth belongs to backend.
- Update `test_result.md` before handing work to a testing agent.
- Verify before claiming done.
- Be honest about skipped checks and failures.

---

## Planning Rules

For non-trivial work, create a short plan before editing.

The plan must include:

1. Current behavior found.
2. Files likely affected.
3. Proposed change.
4. Risks.
5. Verification steps.

For ticketed work, map the plan to the ticket ID and acceptance criteria.

---

## Architecture Rules

- Legacy backend routers live under `backend/routers/`.
- v2 DDD contexts live under `backend/v2/contexts/`.
- v2 BFF routes live under `backend/v2/interfaces/<persona>/`.
- Frontend route groups live under `frontend/app/`.
- Application use cases own workflow orchestration.
- Domain owns business rules.
- Infrastructure owns MongoDB, Firebase, Stripe, Resend, and external adapters.
- Interfaces/BFF own HTTP, persona shaping, auth dependencies, and DTOs.

---

## Non-Negotiables

- Do not commit real secrets, `.env` files, service account JSON, API keys, Stripe keys, or Firebase credentials.
- Do not use `CORS_ORIGINS=*` with cookie auth.
- Do not send real email from local/test environments.
- Do not run production deploys without explicit user approval.
- Do not perform destructive MongoDB operations without explicit user approval.
- Do not rewrite legacy flows into v2 unless the ticket or user asks for that workflow migration.
- Do not mark a phase or wave complete until its exit checklist is actually verified.

---

## Common Commands

Backend:

```bash
cd backend
source .venv/bin/activate
pytest
uvicorn server:app --host 127.0.0.1 --port 8001 --reload
```

Frontend:

```bash
cd frontend
pnpm install
pnpm dev
pnpm typecheck
pnpm build
pnpm generate:api
```

Local testing stack:

```bash
scripts/local_test_stack.sh status
scripts/local_test_stack.sh all
scripts/local_test_stack.sh smoke
scripts/local_test_stack.sh seed
scripts/local_test_stack.sh stop
```

Use this helper for local manual testing. It checks/starts MongoDB,
Firebase Auth emulator, backend, and frontend with the local Firebase/Mongo/BFF
environment wired together. It writes logs and PID files under
`/tmp/academy-manager-local`. `stop` only stops processes started by this
script. The frontend still needs a real public Firebase web API key in
`frontend/.env.local`, `frontend/.env`, or the environment; do not fall back to
`dummy` for Firebase Auth testing.

Container smoke:

```bash
docker compose up --build
curl http://127.0.0.1:8001/api/health
```

---

## Git Rules

Before editing and before finishing:

```bash
git status --short --branch
git diff
```

Commit only related changes. Do not sweep unrelated dirty work into a commit.

All changes to `main` must go through a pull request. Do not push directly to
`main`, and do not merge a feature branch locally into `main`; open a PR, wait
for required checks/review, then merge through GitHub.

Never run without explicit approval:

```bash
rm -rf
git reset --hard
git clean -fd
```

---

## Pre-Push CI Checks

Run these locally before every push. CI will fail the same way if you skip them.

Backend (from `backend/` with `.venv` active):

```bash
ruff check v2
ruff format --check v2
mypy --config-file pyproject.toml v2
pytest v2/tests --override-ini="testpaths=v2/tests" -q
```

Frontend (from `frontend/`):

```bash
pnpm typecheck
pnpm lint
pnpm build
```

If any command fails locally, fix it before pushing. Do not push to unblock CI — that just shifts the problem.

---

## Feedback Loop

Use `docs/agent/feedback-loop.md`.

Minimum loop:

1. Read current status: `git status`, `test_result.md`, tickets if present.
2. Implement the smallest coherent change.
3. Update `test_result.md` with what changed and what needs retesting.
4. Run focused verification.
5. Record results and remaining risks.
6. Update ticket checkboxes only when acceptance criteria are verified.
7. Leave a handoff note if work is incomplete.

---

## Final Response Format

Final response must include:

1. What changed.
2. Files changed.
3. Verification performed.
4. Remaining risks or skipped checks.
5. Next recommended step, if useful.

Keep it short. Do not fake verification.
