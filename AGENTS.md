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

Use the maintained testing runbook: `docs/testing.md`.

`test_result.md` is only an index. Detailed testing state lives in
`docs/test-results/active/`. Create, update, verify, and close task ledgers with
`scripts/dev/test_result.py`; do not manually restore the old global YAML
ledger in `test_result.md`.

---

## Task Routing

| Task type | Read |
| --- | --- |
| Architecture / DDD / BFF / migration plan | `docs/agent/architecture-rules.md` |
| Backend / API / Mongo / auth / payments | `docs/agent/backend-api-rules.md` |
| Frontend / React / UI / PWA | `docs/agent/frontend-rules.md` |
| Testing / verification / bug fixing | `docs/testing.md` and `docs/agent/testing-verification.md` |
| Production-scale local real-user audit | `docs/testing.md` and `docs/agent/testing-verification.md` |
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

## Testing Commands

Testing commands, local stack usage, Docker SaaS staging, rebuild guidance,
pre-push checks, UI verification, and production-scale audit steps live in
`docs/testing.md`.

High-frequency entry points:

```bash
scripts/local_test_stack.sh all
scripts/dev/saas_staging.sh up-dev
scripts/dev/saas_staging.sh blno-seed
scripts/dev/pre-push-checks.sh
```

Use `http://blno.localhost:3000/login` for Docker SaaS BLNO testing and
`http://blno.localhost:3001` for the non-Docker local stack.

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
