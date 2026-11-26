READ ~/Projects/agent-scripts/AGENTS.MD BEFORE ANYTHING (skip if missing).

# AGENTS.md

Agent guidance for `academy-manager`.

Applies to Claude Code, Codex, and any AI coding agent.

This file is the root router. Detailed rules live in `docs/agent/`.

Claude Code-specific automations live under `.claude/` and support this file;
they do not replace it. Non-Claude agents should treat `.claude/` content as
optional, with `AGENTS.md` remaining the canonical cross-agent source of truth.

Agent roles and model routing: `docs/agent/agent-roles.md`. A lead session
routes and merges; pinned agents in `.claude/agents/` (planner, builder,
reviewer, risk-reviewer, mechanical) do the work. Everything else an agent sees
is per-machine global setup, not part of this repo. Also tracked:
`.claude/workflows/fix-issue-batch.js` and `.claude/hooks/` (protected-file
guard, verification reminder).

If cross-session context seems missing, a local `claude-mem` install may hold
it; it is optional and not required for any workflow here.

---

## Review Agents

Every change gets the **reviewer** agent before merge. A change touching the
risk paths in `docs/agent/agent-roles.md` (billing, tenancy, auth, Stripe and
webhooks, migrations, public routes, PII) also gets the **risk-reviewer**. The
**vibesec** skill is an optional generic checklist (IDOR, XSS, CSRF, SSRF) on
top; it does not replace either.

---

## Read First

Before coding, read:

1. `README.md`
2. `DEPLOYMENT.md`
3. The focused rule file for the task.
4. For architecture questions, see `docs/architecture/` — generated diagrams and written analysis live there (see `docs/architecture/generated/README.md` for the index).

If the branch contains `docs/tickets/`, also read:

1. `docs/tickets/README.md`
2. The current phase or wave ticket sheet.
3. Any ADR or policy doc referenced by the ticket.

Do not treat `.claude/worktrees/*` as canonical project source unless the user explicitly asks about that worktree.

---

## Testing

Use the maintained testing runbook: `docs/testing.md`.

The `test_result.md` / `docs/test-results/active/` ledger
(`scripts/dev/test_result.py`) is optional: use it only when handing work to a
separate testing agent that needs a shared written state. Day-to-day work
records verification in the PR and final response instead.

---

## Project Context Docs

- **PROJECT.md** (repo root) — architecture, data flow, design decisions, critical paths. Read before structural changes. Re-verified 2026-11-26; verify against code.
- **GAPS.md** (repo root) — known weaknesses ordered by severity, each with a scoped fix and a status table. Check before "discovering" a bug. Re-verified 2026-11-26.

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
| Agent roles, routing, briefs, lead handoff | `docs/agent/agent-roles.md` |

---

## Project Snapshot

Current production app:

- Backend: FastAPI, Motor/PyMongo, MongoDB, Firebase Admin SDK, Stripe, Resend, APScheduler.
- Frontend: Next.js 16 App Router (OpenNext on Cloudflare Workers), React 19, Tailwind, Firebase Web SDK, PWA.
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
- Verify before claiming done.
- Be honest about skipped checks and failures.

---

## Planning Rules

When the user asks for a plan, or the work is ticketed, the plan must include:

1. Current behavior found.
2. Files likely affected.
3. Proposed change.
4. Risks.
5. Verification steps.

For ticketed work, map the plan to the ticket ID and acceptance criteria.

---

## Architecture Rules

- **The ONLY backend is `backend.v2.main:app`** (FastAPI, all routes `/api/v2/*`). The legacy backend was deleted (commit `7228e5de`), including its leftover `backend/routers/` and `backend/services/` bytecode; never recreate them.
- v2 DDD contexts live under `backend/v2/contexts/`.
- v2 BFF routes live under `backend/v2/interfaces/<persona>/`.
- Frontend route groups live under `frontend/app/`; the frontend is a Next.js app on a Cloudflare Worker via OpenNext, calling same-origin `/api/v2/*` proxied by `frontend/app/api/v2/[...path]/route.ts`.
- Application use cases own workflow orchestration.
- Domain owns business rules.
- Infrastructure owns MongoDB, Firebase, Stripe, Resend, and external adapters.
- Interfaces/BFF own HTTP, persona shaping, auth dependencies, and DTOs.
- Production runs multi-academy SaaS mode since PR #1212 (BLNO, the house academy, plus the Demo Academy); the host picks the academy. The single-academy regime survives in code for local dev and tests — see PROJECT.md §3.3.

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
cd backend && pytest v2/tests -n 4 -q               # the full suite (~9,400 tests); cap workers at 4 locally, each replays migrations against your mongod
cd backend && ruff check v2 && ruff format --check v2
cd backend && PYTHONPATH=.. lint-imports --config pyproject.toml   # DDD boundary contracts (CI-blocking)

# Mypy — CI-blocking at a frozen baseline (audit C1). Run from the REPO ROOT:
mypy --config-file backend/pyproject.toml -p backend.v2 | mypy-baseline filter --baseline-path backend/mypy-baseline.txt --allow-unsynced
# Fixed pre-existing errors? Shrink the baseline with: ... | mypy-baseline sync --baseline-path backend/mypy-baseline.txt

# Frontend (pnpm, from frontend/)
pnpm dev           # port 3001 (Turbopack; webpack dev full-reloads mid-navigation and breaks e2e)
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
- **Migrations** (`backend/v2/migrations/NNNN_*.py`, `version` + `async up(db)`) are the only way to create indexes/validators; in production they are applied by the deploy pipeline, not on boot: the `migrate-production` job in `.github/workflows/production.yml` dry-runs `python -m backend.v2.migrations` on the new image and Fly's `release_command` (`backend/fly.toml`) applies them before traffic moves; `V2_RUN_MIGRATIONS_ON_BOOT` is `false` in prod (see `docs/runbooks/migrations-rollout.md`). New migration = next unused 4-digit prefix, version string must equal the filename stem.
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
- CI coverage gate is `--cov=v2 --cov-fail-under=86` (measured ~88%; composition ~78%, `main.py` ~50%); mypy blocks only NEW errors (~900 pre-existing errors frozen in `backend/mypy-baseline.txt`, burn-down tracked in `docs/audit/mypy-baseline.md`); `backend/scripts/` is excluded from ruff/mypy entirely. Green CI ≠ typed/covered.
- Scheduler, outbox dispatcher, and rate limiting assume a **single Fly machine**. Do not scale out without adding distributed locking.
- Seeding is idempotent-by-count (skips if `academies` non-empty) — a partially seeded DB silently stays partial; use `saas-reset`.
- `.worktrees/` and `.claude/worktrees/` are parallel in-flight branches — not canonical source.
- `frontend` build MUST stay `next build --webpack`. Turbopack builds silently drop the Serwist service worker (no error, no `public/sw.js`). `dev` may use Turbopack.
- Any `next` bump must bump `@opennextjs/cloudflare` in the same PR. e2e runs `next start`, never the Workers runtime; a mismatch 500'd every prod request on 2026-10-29 (#1086). CI now runs `scripts/smoke/worker_runtime_smoke.sh`.
- A new `page.tsx`/`route.ts` under `frontend/app/` breaks four backend inventory tests. In the same commit: add the route to `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`, bump the hardcoded route count in `test_inventory_control_evidence.py` and `test_inventory_acceptance_coverage.py`, and satisfy `scripts/dev/audit_inventory_static_gaps.py`. Check with `pytest v2/tests/unit/test_inventory_*.py v2/tests/unit/test_audit_inventory_manifest.py -q`.
- Unique indexes on optional string fields that also serve lookups: use `partialFilterExpression={field: {"$gt": ""}}`, never `{"$type": "string"}` (the planner ignores `$type` partials for eq/`$in` lookups → COLLSCAN). Avoid `$or` across partial-indexed fields. `explain()` on a real mongod; mongomock evaluates neither partial filters nor plans, and ignores validators.
- Test fakes for stores must copy the real store's refusals (insert-only writes raise on duplicate keys, audit appends dedup). Permissive fakes hid two P1 money bugs on #664.
- A real-Mongo test must use the `real_db` fixture. `db` is mongomock unless `CONTRACT_TESTS_MONGO_URL` is set, so a test written against `db` silently skips the indexes and validators it meant to exercise.
- Real-Mongo contract tests: never run two `pre-push-checks.sh` gates against one mongod (concurrent migration replays crash it). Push branches one at a time with `V2_MONGO_URL` set to your own mongod. Local Mongo is 7.0, prod and CI are 8.0. Start that mongod with `--wiredTigerEngineConfigString "file_manager=(close_idle_time=10,close_scan_interval=5)"`: dropped per-test collections keep their file handles open for WiredTiger's default 10 minutes, and one gate run passes macOS's 61,440 open files per process (`FileNotOpen`, then every test fails on connection refused).
- A failing e2e spec is not "the known flake" until it passes alone on an idle machine.
- A PR with zero CI checks usually has the wrong base or conflicts with `main` (`mergeable_state: dirty`); GitHub dispatches no workflows. Retarget or merge `origin/main`, then push.
- Subagent `isolation: "worktree"` fails here (a local WorktreeCreate hook returns a non-path). Create worktrees by hand: `git worktree add -b <branch> <path> origin/main`, then `ln -sfn <repo>/backend/.venv <path>/backend/.venv`.

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
- Generated/derived files — don't hand-edit: `frontend/lib/api/generated/`, `graphify-out/`, `.open-next/`, `docs/architecture/generated/`.

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

### Required: code review at PR open and after material revisions

Run the `/code-review` skill against the diff before opening a PR (the first
push of a branch), and again after any material revision — new functionality,
changed behavior, or reworked logic pushed to an open PR. Address the
findings — fix them, or explicitly state why a finding is a false positive.
Trivial follow-up pushes (typos, review-feedback nits, release-note stamps)
do not need a re-review. The Codex CLI (`codex exec review`) is no longer
required here; it was prone to long/stalled runs. This is in addition to
`scripts/dev/pre-push-checks.sh` (run automatically by the pre-push hook).

### Required: clean up after your PR lands

Once your PR is pushed (and especially once it merges), reclaim the disk your
session used. Forgotten worktree caches (~1.3 GB of `frontend/node_modules`
plus `backend/.venv` each) have filled the disk before and broken local e2e
runs and Docker with ENOSPC.

Concretely, after your PR merges:

- Remove the worktree you created: `git worktree remove <path>` (from the main
  checkout), then `git worktree prune`.
- If the PR is pushed but not yet merged, at minimum delete the worktree's
  `frontend/node_modules` and `backend/.venv` if you won't return to it soon —
  `pnpm install` and a venv symlink restore them in minutes.
- Never leave a temp checkout under `.claude/worktrees/` or `.worktrees/`
  carrying caches after its branch is merged.

Never run without explicit approval:

```bash
rm -rf
git reset --hard
git clean -fd
```

---

## Release Notes

Write this yourself as part of the change, before pushing — do not leave it
to CI. `.github/workflows/release-notes.yml` is validation-only: it fails when
`backend/` or `frontend/` changed without a complete note, and it never writes
to the PR branch. Write the note before the PR exists with `PR: TBD`: the gate
accepts a complete note added in the PR whose `PR:` line is a placeholder, so
stamping the number never costs an extra push (the release publisher reads it
from the squash subject's `(#NNNN)`). Stamp it on a later push if you have one.
To create a local starting point after the PR number is known, run
`python3 scripts/dev/release_notes_check.py --generate --pr-number <number>`,
then replace every generated placeholder before pushing.

Before merging a PR to `main` (or when batching several PRs into one deploy),
add a file to `docs/release-notes/YYYY-MM-DD-<slug>.md`:

```markdown
# <slug>

PR: #<number>   (or `PR: TBD` before the PR exists)

## What changed
<1-3 sentences, user/operator-facing framing>

## Deploy notes
<migrations to run, env vars, manual steps, or "none">

## Risk / rollback
<what breaks if this is wrong, how to roll back>
```

Keep each file terse — this is a deploy log, not a design doc. Link related
PRs when several land in the same batch. If a PR includes a migration, the
file must say so and note anything the owner should look for in the
`migrate-production` dry-run and the deploy's release_command log (see
`docs/runbooks/migrations-rollout.md`); migrations apply automatically there,
so call out only a migration that needs a manual step or a long backfill.

After every complete production deployment and successful smoke check,
`.github/workflows/production.yml` aggregates the notes added since the last
`deploy-*` tag and publishes an idempotent GitHub Release for the deployed SHA.
Do not move or force-update production tags.

---

## Feedback Loop

Use `docs/agent/feedback-loop.md`.

Minimum loop:

1. Read current status: `git status` and tickets if present.
2. Implement the smallest coherent change.
3. Run focused verification.
4. Record results and remaining risks.
5. Update ticket checkboxes only when acceptance criteria are verified.
6. Leave a handoff note if work is incomplete.

---

## Final Response Format

Final response must cover, in prose (bullets only for genuine lists):

1. What changed.
2. Files changed.
3. Verification performed.
4. Release notes added/updated in `docs/release-notes/`, or why not applicable.
5. Remaining risks or skipped checks.
6. Next recommended step, if useful.

Keep it short. Do not fake verification.
