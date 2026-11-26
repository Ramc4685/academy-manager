# GAPS.md — Honest Audit

*First written 2026-07-07. Re-verified item by item against `main` on 2026-11-26 (PR #1243). Ordered by severity, most important first. Each open gap has a suggested fix scoped small enough for a single focused task. Architecture context: PROJECT.md. Live issue tracker: GitHub issues; this file holds the structural gaps that do not have one.*

Severity legend: **P0** = money/tenant-isolation/security risk, fix before scaling. **P1** = will bite soon or blocks the SaaS roadmap. **P2** = tech debt, inconsistency, hygiene.

Production context that changed the weights: since PR #1212 (2026-11-18) production serves more than one academy (`APP_TENANCY_MODE=multi_academy`, `V2_SAAS_MODE=true`). Tenant-isolation gaps are now live risk, not future risk.

## Status at a glance

| # | Gap | Status (2026-11-26) |
|---|---|---|
| 1 | Boot-frozen `default_academy_id` in compositions | Mostly fixed; `users` fallback residue open |
| 2 | Raw tenant Mongo reads in compositions | Guarded by structural test; repository move still open |
| 3 | Rate-limit keying | Fixed (keying); single-process state open (see 13) |
| 4 | Platform-charge fallback | Fixed in production (house-academy routing) |
| 5 | Weak credentials and real PII in seed scripts | Credentials fixed; **real PII still in `seed_local.py`** |
| 6 | Billing dual model (legacy `Payment`) | Open |
| 7 | Client-only frontend guards | Partly fixed (edge middleware); `(shared)` role check open |
| 8 | E2E never exercises real auth | Fixed |
| 9 | Coverage/mypy gates | Mostly fixed; scripts still unlinted |
| 10 | Duplicate migration prefixes | Open, and grown (7 numbers) |
| 11 | Stripe SDK pin vs Accounts v2 | Pin moved to 16.1.0; 17.0.0 bump open (PR #1189) |
| 12 | Autopay metadata truncation | Open |
| 13 | Single-machine assumptions unguarded | Open |
| 14 | `AdminUseCases` service locator | Open (~200 fields, ~65 `object \| None`) |
| 15 | Ghost directories | Fixed |
| 16 | Root clutter | Fixed |
| 17 | Competing styling systems | Partly fixed |
| 18 | Generated OpenAPI types unused | Fixed |
| 19 | Stubbed membership API | Fixed |
| 20 | Requirements bloat | Partly fixed |
| 21 | Dormant work | Updated list below |
| 22 | Docs sprawl | Open, and grown (~970 files) |

---

## P0 — Security / money / tenant isolation

### 1. Boot-frozen `default_academy_id` in compositions — MOSTLY FIXED
- **Fixed:** coach and parent write paths take a request-time tenant provider (audit C4, #317). MT1 moved the admin report and payout read models out of `composition/admin.py` into context infrastructure.
- **Residue:** `MongoUserRepository(default_academy_id=...)` still falls back to the boot academy (`PRIMARY_ACADEMY_ID`) for legacy `users` rows without `academy_id` (`composition/admin.py:762`, `:1285`, `:4449`, `composition/coach.py:384`, `main.py:713`). Production acknowledges this with `V2_ALLOW_STATIC_TENANT_PARENT_WIRING=true` (startup guard, issue #532, `composition/parent.py` `_STATIC_TENANT_WIRING_NOTE`).
- **Why it matters now:** with two live academies, any `users` row missing `academy_id` resolves to BLNO.
- **Fix (single task):** run `python -m backend.scripts.multi_academy_preflight` against production, backfill `academy_id` on any listed rows with a migration, then remove the fallback and the acknowledgement flag.

### 2. Raw tenant Mongo reads in compositions — GUARDED, NOT MOVED
- **What changed:** `backend/v2/tests/test_no_raw_tenant_mongo_access.py` now scans all of v2, including `composition/` (MT4, 2026-07-21). A raw `db["<tenant collection>"]` call must carry a visible `academy_id` / `_scoped(` signal. The only transitional allowlist entry is `interfaces/admin/progress_routes.py` (inline `audit_logs` insert).
- **Still open:** `composition/parent.py` (~36 sites) and `composition/admin.py` (~44 sites) still query Mongo directly with hand-written `current_academy_id()` filters. The guard is a heuristic ratchet ("a function that mentions `academy_id` is trusted"), not proof of correct scoping, and it still breaks the "interfaces call use cases, not Mongo" rule.
- **Fix (single task, per function):** move each inline query into a read-model repository extending `TenantScopedRepository`. Start with the parent payments/children/enrollments reads. One function per PR.

### 3. Rate limiting — KEYING FIXED
- **Fixed:** `InMemoryRateLimitMiddleware` (`backend/v2/shared/http/rate_limit.py`) keys on `CF-Connecting-IP` when the request carries the proxy shared secret, else `Fly-Client-IP`, else the socket peer. A client cannot forge its key.
- **Still open:** state is process-local. Tracked under item 13.

### 4. Platform-charge fallback — FIXED IN PRODUCTION
- **What changed:** charge routing is one rule, `decide_charge_route` (`contexts/billing/domain/charge_route.py`). `HOUSE_ACADEMY_ID` (BLNO, `backend/fly.toml`) is the only academy that charges on the platform Stripe account. Every other academy takes direct charges on its own connected account, and is refused (`no_account` / `account_not_ready` / `account_platform_liable`) when that account is not ready. `allow_platform_charge_fallback` is derived on read from `HOUSE_ACADEMY_ID` and is read-only to admins (`infrastructure/house_academy.py`, `use_cases/billing_settings_admin.py`).
- **Residue:** the stored per-academy flag is still honoured when `HOUSE_ACADEMY_ID` is unset (local, staging, tests). Keep `HOUSE_ACADEMY_ID` set in every environment that moves real money.

### 5. Credentials and real PII in seed/dev scripts — CREDENTIALS FIXED, PII OPEN
- **Fixed:** `import_blno.py` reads passwords from `BLNO_COACH_PASSWORD` / `BLNO_PARENT_PASSWORD`; `backend/.env.example` uses `admin@example.com` / `CHANGE_ME`; `backend/.env.bak` is gone; `seed_firebase_users.py` has no personal addresses.
- **Still open:** `backend/scripts/seed_local.py` `ROSTER` (from ~line 405) holds about 47 real-looking parent names, personal email addresses and phone numbers.
- **Why it matters:** real families' contact data sits in git history and on every developer machine, and a seed run aimed at a real Firebase project would create accounts for them.
- **Fix (single task):** replace the roster with synthetic names, `*.example.com` emails and 555 numbers. Decide separately whether history needs a scrub.

---

## P1 — Will bite soon / blocks the roadmap

### 6. Billing's dual model: legacy `Payment` repo reads/writes ledger collections (ADR violation) — OPEN
- **What:** ADR-0011 says "neither repository references the other's collection name," but `MongoPaymentRepository` (`collection_name = "payments"`) reads and updates `ledger_payments` as a convergence shim (`backend/v2/contexts/billing/infrastructure/mongo_payment_repo.py:157-180`). `handle_webhook_event.py` still saves legacy `Payment` projections. ADR-0012 Phase 5 (delete legacy `Payment`) is not done.
- **Where:** also `docs/adr/0011-*`, `docs/adr/0012-*`, `backend/scripts/archive_legacy_payments.py`, `docs/runbooks/legacy-payments-retirement.md`.
- **Why it matters:** two sources of financial truth with a cross-shape coupling the ADR banned. Every billing change must be reasoned about twice.
- **Fix (single task):** execute the retirement runbook for drained `payments` rows (audited by `launch_readiness_audit.py::audit_legacy_payment_retirement`), then one task per legacy write site to stop writing `Payment` projections.

### 7. Frontend auth guards — PARTLY FIXED
- **Fixed:** `frontend/middleware.ts` (#451) runs at the edge and settles "no session" and "wrong persona hint" from cookies before the shell paints.
- **Still open:** `(shared)/layout.tsx` checks only signed-in, not role, for `/calendar` and `/messages`.
- **Fix (10 minutes):** make the `(shared)` layout require at least one known role.

### 8. E2E suite never exercises real auth — FIXED
- A blocking CI step runs `real-backend-journeys.spec.ts` under `playwright.ci-real-auth.config.ts` (#1145, #1147), and a `chromium-desktop` Playwright project exists. Most other specs still use `NEXT_PUBLIC_E2E_AUTH_BYPASS=1`.

### 9. Coverage gate / mypy / scripts lint — MOSTLY FIXED
- **Fixed:** CI runs `--cov=v2 --cov-fail-under=86`. mypy is blocking against a frozen baseline (`backend/mypy-baseline.txt`, burn-down in `docs/audit/mypy-baseline.md`).
- **Still open:** `backend/pyproject.toml` ruff `extend-exclude = ["scripts/", "tests/"]` — the scripts that touch production data have no lint.
- **Fix (single task):** run `ruff check backend/scripts`, fix findings, drop `scripts/` from the exclude.

### 10. Duplicate migration prefixes — OPEN, GROWN
- **What:** duplicate numeric prefixes now exist at `0070`, `0145`, `0156`, `0165`, `0176`, `0179` (three modules) and `0180`. Ordering within a prefix relies on alphabetical discovery.
- **Where:** `backend/v2/migrations/`, `runner.py`.
- **Why it matters:** migrations run against production in the deploy `release_command`. A careless renumber could re-run one under a changed version key.
- **Fix (single task):** add a unit test that fails on any *new* duplicate prefix (allowlist the existing ones) and asserts each `version` matches what production recorded. Do not renumber applied migrations.

### 11. Stripe SDK pin vs Accounts v2 API — MOVED
- **What:** the pin is now `stripe==16.1.0` (`backend/requirements.txt`); `stripe_gateway.py` calls `client.v2.core.accounts.create`. Dependabot PR #1189 proposes 17.0.0, a major bump.
- **Fix (single task):** take #1189 through the risk-reviewer, re-run the billing suite and Stripe request-shape contract tests, and exercise Connect onboarding in the staging sandbox.

### 12. Autopay metadata truncation silently drops enrollments — OPEN
- **What:** `_autopay_enrollment_ids_value` (`contexts/billing/infrastructure/stripe_gateway.py:51`) drops trailing enrollment ids past Stripe's 500-char metadata cap, with only a log warning.
- **Fix (single task):** store the enrollment list in Mongo keyed by setup-intent/customer id and put only that key in Stripe metadata.

### 13. Single-machine assumptions are load-bearing but unguarded — OPEN
- **What:** ~30 APScheduler jobs, the outbox dispatcher (no leader election) and the in-memory rate limiter all assume exactly one backend instance. `fly.toml` keeps `min_machines_running = 1` but nothing stops `fly scale count 2`.
- **Fix (single task):** add a startup log/guard tied to an explicit env flag (e.g. `SINGLETON_JOBS=true`) and a DEPLOYMENT.md note that scaling out needs distributed locking first.

---

## P2 — Tech debt, inconsistencies, hygiene

### 14. `AdminUseCases` service locator — OPEN
- **Where:** `backend/v2/interfaces/admin/deps.py` — ~200 fields, ~65 still typed `object | None`.
- **Fix:** one task per admin sub-domain: replace `object` with the real use-case type for one field group (start with billing), fix fallout, repeat.

### 15. Ghost directories and orphaned bytecode — FIXED
- `backend/routers`, `backend/services`, `backend/tests`, `backend/uv.lock`, `.coverage` and `backend/.env.bak` are gone.

### 16. Tracked clutter at repo root — FIXED
- The png, html, `Plans.md` and `output/` are gone. `test_result.md` stays as the documented index.

### 17. Frontend styling has competing systems — PARTLY FIXED
- **Fixed:** `components/ds/button.tsx` and the admin layout use tokens; `globals.css` derives `--rally-*` from the Tailwind config; the duplicated `mapRoleToStatus` is gone.
- **Still open:** ~55 `.tsx` files under `app/` and `components/` still use inline `style={{}}`; the landing page uses CSS modules.

### 18. Generated OpenAPI types — FIXED
- `frontend/lib/api/generated/v2.d.ts` is committed and used by several clients; CI checks frontend API types against the backend contract (#1144).

### 19. Tenant switcher membership API — FIXED
- `GET /api/v2/me/memberships` exists (`interfaces/me_routes.py`) and `frontend/lib/api/v2/memberships.ts` calls it.

### 20. Requirements bloat — PARTLY FIXED
- **Fixed:** `requirements-dev.txt` exists; `openai`, `google-genai`, `tiktoken`, `huggingface_hub`, `boto3` and `mongomock-motor` are out of runtime requirements. AI uses plain `httpx`, no SDK.
- **Still open:** `numpy`, `pandas` and `passlib` remain pinned in `backend/requirements.txt`, but nothing in `backend/v2/` or `backend/scripts/` imports them. Remove them and confirm the Docker image builds and boots.

### 21. Half-finished / dormant work to be aware of
- **WhatsApp channel:** design docs on `docs/whatsapp-channel-design`, and a parked, unfinished OpenWA send port on `feat/whatsapp-group-announcements`. Not on main.
- **Gated personas:** `ENABLE_OWNER_ROLE` and `ENABLE_STUDENT_LOGIN` are false in prod (issue #779). `ENABLE_PLATFORM_ROUTES` is now **true**.
- **Offline writes:** coach attendance queues offline (`frontend/lib/offline/attendance-queue.ts`); the general queue in `queue.ts`/`sync.ts` still covers only the attendance endpoint.
- **Two Stripe Connect onboarding paths** (OAuth URL builder and Accounts-v2 hosted) both remain in `stripe_gateway.py` — pick one before more academies onboard.
- **`_NullPlatformRoleRepository`** in `backend/v2/main.py` (~:3458) appears dead — delete candidate.
- **Duplicate `app.state.bootstrap_academy` assignment** in `_lifespan` (`main.py` ~:792 and ~:2580).
- **Registered no-op event handler** `on_student_placed_in_level` (`composition/event_handlers.py:150`).
- **Quarantined Stripe events need manual replay** — check `stripe_webhook_events` for stuck `quarantined` rows; billing health lists stuck events.
- **Fixed since July:** the `_session_amount_cents` 2500-cent magic default is gone; the first autopay charge on fresh invoices is the attempt-0 dunning rung on an academy charge day (#1181); the old `.worktrees/` checkouts are not in the repo.

### 22. Docs sprawl — OPEN, GROWN
- **What:** ~970 markdown files under `docs/` (release notes, test results, plans, retros). Stale cutover docs (`docs/cutover-w*.md`) describe completed migrations.
- **Fix (single task):** add a `docs/README.md` index marking authoritative docs (security-matrix, adr/, agent/, testing.md, runbooks/) vs historical; move dead cutover docs to `docs/archive/`.
