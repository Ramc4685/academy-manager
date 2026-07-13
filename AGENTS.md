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

## Cross-Session Memory (claude-mem)

This project has `claude-mem` installed for both Claude Code and Codex CLI. It passively captures session activity and injects relevant prior context automatically — it does not replace the curated project memory an agent may keep separately, and it does not replace Headroom (Headroom is in-session context compression; claude-mem is cross-session recall). No explicit invocation is required in normal work. If cross-session context seems missing or stale, run `claude-mem search <query>` to check before assuming it doesn't exist.

---

## Security Review

For any change touching authentication, authorization, tenant isolation, Stripe, Firebase, Resend, cookies, CORS, secrets, webhooks, payments, or production deploy paths:

1. Use the **security-reviewer** subagent (`.claude/agents/security-reviewer.md`) — it is the primary, academy-manager-specific review (tenant scoping, webhook idempotency, Firebase token handling).
2. The **vibesec** skill supplements it with a general web-vulnerability checklist (IDOR, XSS, CSRF, SSRF, SQLi, JWT, file upload, path traversal). It is not a substitute for the project-specific checks above — use it to catch generic classes the subagent's checklist doesn't enumerate line-by-line.

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

## Project Context Docs

- **PROJECT.md** (repo root) — architecture, data flow, design decisions, critical paths. Read before structural changes.
- **GAPS.md** (repo root) — known weaknesses ordered by severity, each with a scoped fix. Check before "discovering" a bug.

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

- **The ONLY backend is `backend.v2.main:app`** (FastAPI, all routes `/api/v2/*`). The legacy backend was deleted (commit `7228e5de`); `backend/routers/` and `backend/services/` contain only orphaned `.pyc` — never read them as source.
- v2 DDD contexts live under `backend/v2/contexts/`.
- v2 BFF routes live under `backend/v2/interfaces/<persona>/`.
- Frontend route groups live under `frontend/app/`; the frontend is a Next.js app on a Cloudflare Worker via OpenNext, calling same-origin `/api/v2/*` proxied by `frontend/app/api/v2/[...path]/route.ts`.
- Application use cases own workflow orchestration.
- Domain owns business rules.
- Infrastructure owns MongoDB, Firebase, Stripe, Resend, and external adapters.
- Interfaces/BFF own HTTP, persona shaping, auth dependencies, and DTOs.
- Production runs single-academy mode (BLNO); the code is SaaS-shaped. Two tenancy regimes coexist — see PROJECT.md §3.3.

---

## Commands

```bash
# Local dev stack (bare-metal: Mongo + Firebase emulator + backend :8001 + frontend :3001)
scripts/local_test_stack.sh fresh        # full reset + seed + smoke
scripts/local_test_stack.sh test         # backend pytest + frontend typecheck

# Docker SaaS staging (frontend :3000, api :8001, firebase :4000, mongo :27017)
make up            # saas-up + seed + status   (wraps scripts/dev/saas_staging.sh)
make saas-down / saas-reset / saas-nuke

# Backend
cd backend && pytest v2/tests -n auto -q            # the test suite (~2280 tests)
cd backend && ruff check v2 && ruff format --check v2
cd backend && lint-imports --config pyproject.toml   # DDD boundary contracts (CI-blocking)
cd backend && mypy --config-file pyproject.toml v2   # advisory only

# Frontend (pnpm, from frontend/)
pnpm dev           # port 3001
pnpm typecheck && pnpm lint && pnpm build
pnpm e2e           # Playwright mobile projects, auth-bypassed
pnpm e2e:local-auth  # real-auth suite (separate config, not in CI)

# Deploy (via CI only — .github/workflows/production.yml with manual approval gate)
# backend: flyctl deploy --remote-only --app courtmastr-academy-api
# frontend: pnpm deploy:cloudflare
```

Run backend commands from `backend/` (or repo root with `PYTHONPATH=.`); modules are addressed `backend.v2.*`.

---

## Conventions This Codebase Actually Follows

- **DDD layering** in `backend/v2`: `contexts/<name>/{domain,application,infrastructure}`; Protocols in `application/ports.py`; one class per use case in `application/use_cases/`. Enforced by import-linter + structural pytest tests — if `lint-imports` or `tests/structural/` fails, fix your layering, don't loosen the contract.
- **BFF routes are persona-shaped** (`interfaces/{admin,coach,parent,platform}`), never generic CRUD. Routes call use cases from `request.app.state.*`; they never touch Mongo. Wrong-persona access returns **404, not 403** (deliberate; see `docs/security-matrix.md`).
- **Tenancy:** every tenant-owned repo extends `TenantScopedRepository` (`backend/v2/shared/tenancy/repository.py`); application code never sees `academy_id`. Read tenant at execution time via `current_academy_id()` / `tenant_scope(...)` — **never capture academy_id in a composition-time closure** (past prod-bug class) and never use `default_academy_id` in SaaS request paths.
- **Migrations** (`backend/v2/migrations/NNNN_*.py`, `version` + `async up(db)`) are the only way to create indexes/validators; they run on production boot. New migration = next unused 4-digit prefix, version string must equal the filename stem.
- **New/changed v2 routes must be registered** in the audit inventory manifest (see `backend/v2/tests/unit/test_audit_inventory_manifest.py`) or tests fail.
- **Frontend:** everything is effectively client components + TanStack Query v5 (query keys centralized in `frontend/lib/query/keys.ts`); all API calls go through `lib/api/client.ts` `apiFetch`; forms are plain controlled state; styling should use Tailwind `rally-*` tokens (inline hex styles exist but are debt — don't add more).
- **Money is integer cents** (`amount_cents`); ids are string ULIDs (`backend/v2/shared/ids.py`); scheduler timezone `America/Chicago`.
- Errors: domain errors subclass per-context error types; HTTP mapping happens in interfaces; the frontend `ApiError` handles both `{error:{code,message}}` and FastAPI `{detail}` shapes.

---

## Gotchas

- "Legacy" means three different things: the deleted pre-v2 app (history only), single-tenant compat adapters inside v2 (`_LegacyUserMembershipAdapter`), and the legacy `Payment` billing model mid-retirement. Check which one your doc/comment means.
- Env config is two-tier: `V2_FOO` falls back to plain `FOO` (`backend/v2/shared/config/settings.py`). Grep both before declaring a variable unused.
- The Stripe webhook route lives on the **parent** router (`/api/v2/parent/webhooks/stripe`), signature-as-auth; events are accepted fast and **processed by a 60s scheduler job**, not in-request. Local Stripe testing: `scripts/dev/saas_staging.sh stripe-listen` (must forward `account.updated` and `capability.*` Connect events too).
- Bearer tokens are accepted from three headers: `Authorization`, `x-courtmastr-auth`, `x-courtmastr-identity` (the frontend proxy bridge translates the latter).
- Migration `0128` is imported via `importlib` by string name (digit-leading module) — not greppable as a normal import.
- E2E runs with `NEXT_PUBLIC_E2E_AUTH_BYPASS=1` (fake Firebase user) — passing e2e does NOT prove auth works; use the local-auth config for that.
- CI coverage gate only covers `v2/shared` (70%); mypy is advisory; `backend/scripts/` is excluded from ruff/mypy entirely. Green CI ≠ typed/covered.
- Scheduler, outbox dispatcher, and rate limiting assume a **single Fly machine**. Do not scale out without adding distributed locking.
- Seeding is idempotent-by-count (skips if `academies` non-empty) — a partially seeded DB silently stays partial; use `saas-reset`.
- `.worktrees/` and `.claude/worktrees/` are parallel in-flight branches — not canonical source.

---

## Non-Negotiables

- Do not commit real secrets, `.env` files, service account JSON, API keys, Stripe keys, or Firebase credentials.
- Do not use `CORS_ORIGINS=*` with cookie auth.
- Do not send real email from local/test environments.
- Do not run production deploys without explicit user approval.
- Do not perform destructive MongoDB operations without explicit user approval.
- Do not rewrite legacy flows into v2 unless the ticket or user asks for that workflow migration.
- Do not mark a phase or wave complete until its exit checklist is actually verified.
- **Never weaken:** `backend/v2/shared/tenancy/*`, `shared/auth/middleware.py`, `load_auth_claims.py`, `contexts/billing/domain/ledger.py`, webhook handling/dedup, the import-linter contracts, the structural tests, `docs/security-matrix.md` semantics (404-on-wrong-persona), CORS wildcard rejection in `main.py`.
- **Migrations are append-only** once merged; never renumber or edit an applied migration — write a new one.
- **`backend/scripts/archive_legacy_payments.py` is destructive and manual** — never run or automate without the runbook (`docs/runbooks/legacy-payments-retirement.md`).
- Generated/derived files — don't hand-edit: `frontend/lib/api/generated/`, `graphify-out/`, `.open-next/`, `docs/architecture/generated/`, release notes (CI-generated).

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

### Required: code review before every push

Before every `git push`, run the `/code-review` skill against the diff and
address the findings — fix them, or explicitly state why a finding is a false
positive. The Codex CLI (`codex exec review`) is no longer required here; it
was prone to long/stalled runs. Push only after the review is clean or every
finding is dispositioned. This is in addition to
`scripts/dev/pre-push-checks.sh` (run automatically by the pre-push hook).

Never run without explicit approval:

```bash
rm -rf
git reset --hard
git clean -fd
```

---

## Release Notes

Write this yourself as part of the change, before pushing — do not leave it
to CI. `.github/workflows/release-notes.yml` auto-generates a stub and
comments on the PR if `backend/` or `frontend/` changed and no file exists,
and fails the check if one exists but a section is empty/placeholder — but
that stub is a backstop, not a substitute for you writing accurate Deploy
notes and Risk/rollback before review.

Before merging a PR to `main` (or when batching several PRs into one deploy),
add a file to `docs/release-notes/YYYY-MM-DD-<slug>.md`:

```markdown
# <slug>

PR: #<number>

## What changed
<1-3 sentences, user/operator-facing framing>

## Deploy notes
<migrations to run, env vars, manual steps, or "none">

## Risk / rollback
<what breaks if this is wrong, how to roll back>
```

Keep each file terse — this is a deploy log, not a design doc. Link related
PRs when several land in the same batch. If a PR includes a migration, the
file must say whether it runs automatically (`run_migrations_on_boot`) or
needs a manual step, since that isn't tracked anywhere else today.

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
4. Release notes added/updated in `docs/release-notes/`, or why not applicable.
5. Remaining risks or skipped checks.
6. Next recommended step, if useful.

Keep it short. Do not fake verification.
