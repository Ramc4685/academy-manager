# AGENTS.md

Agent guidance for `academy-manager`.

Applies to Claude Code, Codex, and any AI coding agent.

This file is the root router. Detailed rules live in `docs/agent/`.

Claude Code-specific automations may live under `.claude/` (hooks, skills,
and subagents). Those automations support this file; they do not replace it.
Non-Claude agents should treat `.claude/` content as optional supporting
guidance, with `AGENTS.md` remaining the canonical cross-agent source of truth.

---

## MCP Servers

Always use **Headroom MCP** when it is available. Use it proactively for any task where memory, context retrieval, or cross-session knowledge would help — do not wait to be asked. If Headroom is not connected, proceed without it but note the gap.

---

## Read First

Before coding, read:

1. `README.md`
2. `DEPLOYMENT.md`
3. `test_result.md`
4. The relevant active ledger under `docs/test-results/active/`, if one exists.
5. The focused rule file for the task.
6. For architecture questions, see `docs/architecture/` — generated diagrams and written analysis live there (see `docs/architecture/generated/README.md` for the index).

If the branch contains `docs/tickets/`, also read:

1. `docs/tickets/README.md`
2. The current phase or wave ticket sheet.
3. Any ADR or policy doc referenced by the ticket.

Do not treat `.claude/worktrees/*` as canonical project source unless the user explicitly asks about that worktree.

---

## Test Result Kickoff

`test_result.md` is only an index. Detailed testing state lives in
`docs/test-results/active/`.

At the start of a task:

```bash
git status --short --branch
sed -n '1,160p' test_result.md
ls docs/test-results/active
```

If there is no active ledger for the task, create one:

```bash
scripts/dev/test_result.py start "task title" --problem "What needs to be verified"
```

During and after work, update the task ledger:

```bash
scripts/dev/test_result.py log task-title --agent main --status working --message "What changed"
scripts/dev/test_result.py verify task-title --message "Command/result or skipped check reason"
scripts/dev/test_result.py close task-title
```

Do not manually restore the old global YAML ledger in `test_result.md`.

---

## Task Routing

| Task type | Read |
| --- | --- |
| Architecture / DDD / BFF / migration plan | `docs/agent/architecture-rules.md` |
| Backend / API / Mongo / auth / payments | `docs/agent/backend-api-rules.md` |
| Frontend / React / UI / PWA | `docs/agent/frontend-rules.md` |
| Testing / verification / bug fixing | `docs/agent/testing-verification.md` |
| Status handoff / agent loop / ticket updates | `docs/agent/feedback-loop.md` |
| Drafting Codex prompts / goals / agent handoffs | `docs/agent/codex-prompting.md` |

---

## Project Snapshot

Current production app:

- Backend: FastAPI, Motor/PyMongo, MongoDB, Firebase Admin SDK, Stripe, Resend, APScheduler.
- Frontend: Next.js 15 App Router, React 19, Tailwind, Firebase Web SDK, PWA.
- Auth: Firebase Authentication in production; legacy password auth can be disabled with `FIREBASE_AUTH_ENABLED=true`.
- Deployment: Fly.io backend app `courtmastr-academy-api`; Cloudflare Worker frontend `academy-next`.
- Local services: backend `http://127.0.0.1:8001`, frontend `http://localhost:3001`, MongoDB `mongodb://127.0.0.1:27017`, Firebase Auth emulator `http://127.0.0.1:9099`. Start everything with `scripts/local_test_stack.sh all`.

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
## Billing safety rules:
- App ledger owns invoices.
- Stripe owns payment collection.
- Redirects never prove payment success.
- Webhooks update ledger state.
- Failed payments do not close invoices.
- Payment attempts record failure.
- Ledger payments record received money.
- Payment allocations must be idempotent.
- Paid invoices cannot be double-paid.
- Duplicate Stripe obligations quarantine.
- Replay must converge state.
- Admin must see unrecovered failures.
## Golden Rules

- Read existing code before editing.
- Make small, surgical changes.
- Preserve working behavior.
- Keep legacy bug fixes isolated from v2 migration work.
- Follow DDD boundaries in `backend/v2`.
- Keep BFF APIs persona-shaped, not generic CRUD.
- Keep frontend presentation-focused; business truth belongs to backend.
- Use `scripts/dev/test_result.py` before handing work to a testing agent.
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
uvicorn backend.v2.main:app --host 127.0.0.1 --port 8001 --reload
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

Pre-push checks (run before every `git push`):

```bash
# Install once after cloning — git will run checks automatically on every push
scripts/dev/install-hooks.sh

# Run manually at any time
scripts/dev/pre-push-checks.sh          # skips E2E unless e2e/ files changed
scripts/dev/pre-push-checks.sh --full   # always runs E2E
```

What the script checks (mirrors CI exactly):

| Check | Command |
| --- | --- |
| Backend format | `ruff format --check v2` (must use `.venv` — system ruff differs) |
| Backend lint | `ruff check v2` |
| Backend tests | `pytest v2/tests -q` |
| Frontend unit | `node --no-warnings --test lib/api/*.node-test.mjs lib/auth/*.node-test.mjs` |
| Frontend types | `pnpm typecheck` |
| Frontend lint | `pnpm lint` |
| E2E | `pnpm e2e` (auto-skipped unless `e2e/` files changed; `--full` forces it) |

**Always activate the backend `.venv` before running ruff manually.** The system ruff
version differs from CI's and will produce false "already formatted" results.

**Never push without running this first. If it fails locally, fix it — do not push to unblock CI.**

Local testing stack (recommended — use this for all manual testing):

```bash
scripts/local_test_stack.sh fresh     # FULL RESET: stop → start everything → seed demo data
scripts/local_test_stack.sh all       # start everything (skips already-running) + smoke check
scripts/local_test_stack.sh status    # show what is running and on which port
scripts/local_test_stack.sh infra     # start MongoDB + Firebase Auth emulator only
scripts/local_test_stack.sh app       # start backend + frontend only (infra must be up)
scripts/local_test_stack.sh smoke     # hit health endpoints and report status
scripts/local_test_stack.sh seed      # load demo data into local MongoDB
scripts/local_test_stack.sh test      # run backend v2 tests + frontend typecheck
scripts/local_test_stack.sh logs      # tail all service logs
scripts/local_test_stack.sh stop      # stop only processes started by this script
```

This starts MongoDB, Firebase Auth emulator, backend (FastAPI `--reload`), and
frontend (`pnpm dev`) with all services wired together. Logs and PID files go
under `/tmp/academy-manager-local`. Frontend runs on port `3001`.

One-time setup: create `frontend/.env.local` with the real Firebase Web API key
(copy from `frontend/.env.example` and fill in `NEXT_PUBLIC_FIREBASE_API_KEY`).
The script also falls back to `REACT_APP_FIREBASE_API_KEY` in `frontend/.env`
if `.env.local` is absent. Never use `dummy` — Firebase Auth will fail silently.

Local Firebase/Auth testing guardrails:

- Prefer `scripts/local_test_stack.sh all` over ad hoc `pnpm dev` restarts. The
  helper sets all required env vars automatically.
- Next.js client code reads `NEXT_PUBLIC_FIREBASE_*` only. `REACT_APP_FIREBASE_*`
  values in `frontend/.env` do not reach the browser directly.
- Frontend Auth emulator URL must include a protocol:
  `NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST=http://127.0.0.1:9099`.
  Backend Admin SDK uses host:port only: `FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099`.
- After starting the frontend, open a browser and sign in to confirm Firebase
  calls reach the Auth emulator without `auth/invalid-api-key`.
- For local BLNO tenant testing, use `http://blno.localhost:3001` — the seed registers the academy with `slug: "blno"` and the backend starts with `V2_DEFAULT_ACADEMY_ID=blno`. Plain `http://localhost:3001` also works (falls back to `default_academy_id`).

Container smoke (build verification only — NOT for real testing):

```bash
docker compose up --build
curl http://127.0.0.1:8001/api/v2/healthz
```

Docker uses a hardcoded `dummy` Firebase API key so Firebase Auth will not work.
Use it only to verify the app builds and the health endpoint responds.

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

## Feedback Loop

Use `docs/agent/feedback-loop.md`.

Minimum loop:

1. Read current status: `git status`, `test_result.md`, the relevant `docs/test-results/active/` ledger, and tickets if present.
2. Implement the smallest coherent change.
3. Use `scripts/dev/test_result.py log` or `verify` to record what changed and what needs retesting.
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
