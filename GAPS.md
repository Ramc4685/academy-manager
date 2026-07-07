# GAPS.md — Honest Audit

*Written 2026-07-07 from a fresh full-codebase exploration. Ordered by severity, most important first. Each gap has a suggested fix scoped small enough for a single focused task. Architecture context: PROJECT.md.*

Severity legend: **P0** = money/tenant-isolation/security risk, fix before scaling. **P1** = will bite soon or blocks the SaaS roadmap. **P2** = tech debt, inconsistency, hygiene.

---

## P0 — Security / money / tenant isolation

### 1. Coach write paths bake `default_academy_id` in at boot
- **What:** `MarkAttendance`, `BulkMarkAttendance`, and `CoachAddStudentToRoster` are composed with `academy_id` captured in a boot-time closure from `settings.default_academy_id` (explicit TODO in code). Reads on the coach surface already use the request ContextVar; these writes don't.
- **Where:** `backend/v2/composition/coach.py` (~lines 222, 242, 350–379; TODO at :371). Same pattern residue in `backend/v2/composition/admin.py` (~:2560, :2941).
- **Why it matters:** In any multi-academy process, coach attendance/roster writes would land in the wrong tenant. This exact bug class already happened once (self-cancel fee line, fixed in PR #289). It is the single biggest blocker to flipping `APP_TENANCY_MODE=multi_academy`.
- **Fix (single task):** Replace the closure-captured `academy_id` in those three use cases with request-time `current_academy_id()` (mirror the fix in `composition/parent.py:645`), then delete the TODO and add a tenant-isolation test per write path.

### 2. Parent read models bypass `TenantScopedRepository` with hand-rolled filters
- **What:** Large inline functions in the parent composition (`list_payments_for_parent`, `list_children_for_parent`, `list_enrollments_for_parent`, `list_attendance_for_parent`, `list_progress_for_parent`, `get_academy_info`, …) query `db["students"]`, `db["enrollments"]`, `db["ledger_payments"]`, etc. directly with manually copied `{"academy_id": ...}` filters.
- **Where:** `backend/v2/composition/parent.py`.
- **Why it matters:** Tenant isolation on the highest-traffic parent surface is enforced by convention, one hand-written filter at a time. One missed filter = cross-tenant data leak of children/payments. It also violates the project's own "interfaces call use cases, not Mongo" rule.
- **Fix (single task, per function):** Move each inline query into a read-model repository extending `TenantScopedRepository` (drop the manual academy_id). Do them one function per PR; extend the structural test `test_no_raw_tenant_mongo_access.py` to cover `composition/`.

### 3. Rate limiting is in-memory, per-process, and nearly absent
- **What:** `InMemoryRateLimitMiddleware` covers only parent registration/onboarding routes, keyed on `request.client.host` (behind Cloudflare/Fly that may be the proxy IP), and state is process-local.
- **Where:** `backend/v2/shared/http/rate_limit.py`; wiring in `backend/v2/main.py:565`.
- **Why it matters:** Scaling Fly beyond one machine silently voids the limits; keying on proxy IP can rate-limit everyone at once or no one. Public endpoints (registration, webhook ingest) are the abuse surface.
- **Fix (single task):** Key on the first `X-Forwarded-For` / `Fly-Client-IP` hop with a trusted-proxy check; document the single-machine constraint in the middleware docstring. (A shared-store limiter is a later task — don't add Redis casually.)

### 4. Platform-charge fallback can silently park academy money on the platform account
- **What:** `allow_platform_charge_fallback` (documented TEMPORARY) charges the **platform** Stripe account when a connected account isn't charge-ready. `application_fee_amount=0` everywhere and there is no automated sweep/transfer, so fallback funds sit on the platform with only out-of-band remediation.
- **Where:** `backend/v2/contexts/billing/application/use_cases/billing_settings_admin.py`, `start_checkout.py`, `charge_invoice_via_autopay.py`, invoice checkout path.
- **Why it matters:** Money owed to an academy accumulates in the wrong Stripe account; reconciliation is manual. The flag exists because the platform's live Stripe account activation was the real blocker (July 2026 502 incident) — once activation lands, the flag becomes a pure liability.
- **Fix (single task):** Add an admin billing-health surface (or extend the existing one) that counts and lists payments taken via fallback (identifiable by missing `transfer_data`), so the owed-to-academy amount is always visible. Follow-up task: remove the flag once Connect is fully activated.

### 5. Committed weak credentials and real PII in seed/dev scripts
- **What:** `import_blno.py:31-32` hardcodes `Coach@12345`/`Parent@12345`; `seed_firebase_users.py` hardcodes real personal emails; `seed_local.py:2119-2125` prints admin credentials to stdout; `backend/.env.example` ships a real admin email and `ADMIN_PASSWORD=Admin@12345`. `backend/.env` and `.env.bak` sit in the working tree (verify never committed: `git log --all -- backend/.env`). Also confirm `firebase-debug.log` history is clean.
- **Where:** `backend/scripts/import_blno.py`, `backend/scripts/seed_firebase_users.py`, `backend/scripts/seed_local.py`, `backend/.env.example`.
- **Why it matters:** Dev-only, but the passwords follow a guessable pattern, the emails are real people, and a misdirected seed run (pointed at real Firebase instead of the emulator) would create weak real accounts.
- **Fix (single task):** Replace hardcoded passwords with generated ones printed once (the `saas_staging.sh` pattern already does this), swap real emails for `*.example.com`, scrub `.env.example` placeholders, and delete `.env.bak`.

---

## P1 — Will bite soon / blocks the roadmap

### 6. Billing's dual model: legacy `Payment` repo now reads/writes ledger collections (ADR violation)
- **What:** ADR-0011 says "neither repository references the other's collection name," but `MongoPaymentRepository.save/get` read and update `ledger_payments` (and read `invoices`/`invoice_lines`) as a convergence shim. Legacy `Payment` projections are still written on subscription `invoice.paid`. ADR-0012 Phase 5 (delete legacy `Payment`) is not done; physical retirement of copied rows is pending a runbook.
- **Where:** `backend/v2/contexts/billing/infrastructure/mongo_payment_repo.py` (:261–299, :633–638); `docs/adr/0011-billing-ledger-payment-storage.md`, `docs/adr/0012-ledger-invoice-as-source-of-truth.md`; `backend/scripts/archive_legacy_payments.py`; `docs/runbooks/legacy-payments-retirement.md`.
- **Why it matters:** Two sources of financial truth with a cross-shape coupling the ADR explicitly banned. Every billing change must be reasoned about twice; drift here is a money bug.
- **Fix (single task):** Execute the documented retirement runbook for the drained `payments` rows (audited by `launch_readiness_audit.py::audit_legacy_payment_retirement`), then one follow-up task per legacy write-site to stop writing `Payment` projections.

### 7. Frontend auth guards are client-only; `(shared)` routes skip role checks
- **What:** No `middleware.ts`; guards run in `usePersonaAuth` after hydration (protected-route JS ships to unauthorized users, visible redirect flashes, and a 1s `window.location.replace` fallback timer papering over flaky `router.replace`). `(shared)/layout.tsx` checks only signed-in, not role, for `/calendar` and `/messages`.
- **Where:** `frontend/lib/auth/use-persona-auth.ts`, `frontend/app/(shared)/layout.tsx`, persona `layout.tsx` files.
- **Why it matters:** The backend enforces authorization, so this is not an access-control hole per se, but it leaks bundle/route structure, degrades UX, and the `(shared)` role-lessness will surprise anyone adding role-specific content there.
- **Fix (single task):** Decide and document: either accept client-only guarding, or add a minimal `middleware.ts` checking `__cm_identity` cookie presence for the persona route groups. Separately (10 minutes): make `(shared)` layout require at least one known role.

### 8. E2E suite never exercises real auth
- **What:** All CI Playwright specs run with `NEXT_PUBLIC_E2E_AUTH_BYPASS=1` and a fake Firebase user baked into `frontend/lib/auth/firebase.ts`. Role-guard redirects, the identity header/cookie bridge, and token refresh have zero end-to-end coverage in CI. Only mobile viewports are configured; the desktop admin surface is untested at its real size.
- **Where:** `frontend/playwright.config.ts`, `frontend/lib/auth/firebase.ts` (`fakeE2EUser`), `frontend/e2e/`; the local-auth config (`playwright.local-auth.config.ts`) exists but is not in CI.
- **Fix (single task):** Add one CI job running `pnpm e2e:local-auth` against the emulator stack with a login → `/me` → persona-redirect smoke spec. Second small task: add a `chromium-desktop` project for 2–3 admin specs.

### 9. Coverage gate covers only `v2/shared`; mypy advisory; scripts unlinted
- **What:** CI's `--cov-fail-under=70` applies to `v2/shared` only; the 10 contexts and all interfaces have no enforced coverage floor. mypy runs `continue-on-error`. `backend/scripts/` is excluded from ruff **and** mypy entirely — the code that touches production data for migrations/audits has no static safety net.
- **Where:** `.github/workflows/production.yml`; `backend/pyproject.toml` (ruff `extend-exclude`, mypy `files=["v2"]`).
- **Why it matters:** Coverage regressions in billing/enrollment can't fail CI; typed-Python guarantees don't exist where people assume they do.
- **Fix (single task):** Widen coverage to `--cov=v2` with the floor set just below the current measured value so it ratchets. Separate task: run `ruff check backend/scripts`, fix findings, remove the exclude.

### 10. Duplicate migration prefixes and inconsistent version strings
- **What:** Two `0070_*` modules (one with version literally `"0070"`) and two `0145_*` modules. Ordering within a shared prefix relies on pkgutil's alphabetical discovery.
- **Where:** `backend/v2/migrations/0070_billing_proration_indexes.py`, `0070_admin_student_directory_indexes.py`, `0145_backfill_student_billing_enrollments.py`, `0145_parent_self_service.py`; `backend/v2/migrations/runner.py`.
- **Why it matters:** Migrations run on production boot. A same-prefix ordering assumption or a careless renumber could apply migrations out of order or re-run one under a changed version key.
- **Fix (single task):** Renumber the later duplicate of each pair to a fresh prefix while keeping the registry `version` string identical to what production already recorded; add a unit test asserting all module prefixes are unique and every `version` matches its filename.

### 11. Stripe SDK version pin vs Accounts v2 API
- **What:** `stripe==15.1.0` is pinned while `stripe_gateway.py` calls `client.v2.core.accounts.create`; a prior session recorded this SDK version lacking parts of the v2 accounts namespace. All fund-moving tests fake the gateway, so a runtime API mismatch would surface only in staging/production.
- **Where:** `backend/requirements.txt`; `backend/v2/contexts/billing/infrastructure/stripe_gateway.py`.
- **Fix (single task):** Exercise the connect-onboarding path in the staging sandbox against the pinned SDK; if it fails, bump the pin and re-run the billing suite plus the Stripe request-shape contract tests.

### 12. Autopay metadata truncation silently drops enrollments
- **What:** Stripe metadata values cap at 500 chars; `_autopay_enrollment_ids_value` drops trailing enrollment ids with only a log warning — parents with many enrollments silently don't get autopay activated for the dropped ones.
- **Where:** `backend/v2/contexts/billing/` (`save_payment_method_for_autopay` path).
- **Fix (single task):** Store the enrollment list in Mongo keyed by setup-intent/customer id and put only that key in Stripe metadata.

### 13. Single-machine assumptions are load-bearing but unguarded
- **What:** APScheduler jobs, the outbox dispatcher (no leader election; 5-min orphan reclaim), and in-memory rate limiting all assume exactly one backend instance. Nothing prevents `fly scale count 2`.
- **Where:** `backend/v2/main.py` (scheduler wiring), `backend/v2/shared/events/dispatcher.py`, `backend/v2/shared/http/rate_limit.py`.
- **Fix (single task):** Add a startup log/guard tied to an explicit env flag (e.g. `SINGLETON_JOBS=true`) and a DEPLOYMENT.md note that scaling out requires distributed locking first. Cheap insurance against an innocent scale-up.

---

## P2 — Tech debt, inconsistencies, hygiene

### 14. `AdminUseCases` is a ~180-field, mostly `object | None` service locator
- **Where:** `backend/v2/interfaces/admin/deps.py`.
- **Why:** Type erasure defeats mypy across the admin surface; optional-everything hides wiring mistakes until runtime.
- **Fix:** Incremental — one task per admin sub-domain: replace `object` with the real use-case type for one field group (start with billing), fix fallout, repeat.

### 15. Ghost directories and orphaned bytecode
- **Where:** `backend/routers/__pycache__/`, `backend/services/__pycache__/` (source deleted in commit `7228e5de`, bytecode remains), empty `backend/tests/`, near-empty `backend/uv.lock`, `.coverage`, `backend/.env.bak`.
- **Why:** Actively misleads newcomers into thinking the legacy app still exists; it burned time in this very audit.
- **Fix (single task):** Delete `backend/routers`, `backend/services`, `backend/tests`, `backend/.env.bak`, `backend/uv.lock`; ensure `__pycache__/` is ignored.

### 16. Tracked clutter at repo root
- **Where:** `production-admin-login-redirect.png` (487 KB tracked binary), `academy-financial-flows.html`, `Plans.md`, tracked `output/` (Playwright artifacts), mutable tracked `test_result.md` scratch index.
- **Fix (single task):** Move the png/html under `docs/` or delete; gitignore `output/`; leave `test_result.md` (it's the documented index) but nothing else mutable at root.

### 17. Frontend styling has three competing systems
- **What:** Tailwind `rally-*` tokens vs. extensive inline `style={{}}` with hardcoded hex (`#0a0f1c`, `#facc15`) in persona layouts and even `components/ds/button.tsx`, vs. CSS-modules on the landing page. Colors are defined in ≥3 places (tailwind.config, inline, `globals.css` vars). `mapRoleToStatus` is duplicated (`frontend/app/(admin)/admin/users/page.tsx:73` and `AdminUsersDirectory.tsx:259`), both returning `any`.
- **Fix:** One task per surface: convert `components/ds/button.tsx` to Tailwind tokens first (highest leverage), then the admin layout. Separate 10-minute task: dedupe `mapRoleToStatus` into one typed helper.

### 18. Generated OpenAPI types wired but unused
- **What:** `pnpm generate:api` produces `lib/api/generated/v2.d.ts` (CI even checks drift against `openapi.snapshot.json`), but the directory holds only `.gitkeep` and all v2 clients hand-roll their interfaces.
- **Where:** `frontend/lib/api/generated/`, `frontend/package.json`.
- **Fix (single task):** Commit the generated types and convert one client (`frontend/lib/api/v2/sessions.ts`) to consume them as the template.

### 19. Tenant switcher runs on a stubbed membership API
- **What:** `frontend/lib/api/v2/memberships.ts::listMyMemberships` returns a fake single-academy list (TODO wave5-A); no `/me/memberships` BFF route exists, so the admin `TenantSwitcher` shows a derived placeholder.
- **Fix (single task):** Add `GET /api/v2/me/memberships` backed by the membership repository and swap the stub.

### 20. Requirements bloat and misplaced dev deps
- **What:** `backend/requirements.txt` pins ~136 packages including an ML/data stack the API doesn't use (`openai`, `google-genai`, `tiktoken`, `huggingface_hub`, `boto3`, `pandas`, `numpy`), test doubles (`mongomock-motor`), and legacy auth libs (`passlib`, `python-jose`) needed only by seed scripts. `pip-audit` is the only unpinned line.
- **Fix (single task):** Split runtime vs dev/tooling requirements; verify the Docker image builds and boots; expect a much smaller image and faster deploys.

### 21. Half-finished / dormant work to be aware of (not necessarily to fix)
- **Wave 1B offline writes:** `frontend/lib/offline/{queue,sync,idb,audit}.ts` scaffolded, intentionally inert; the "IndexedDB" query persistence actually uses localStorage (documented workaround, misleading name).
- **Gated personas:** `ENABLE_STUDENT_LOGIN`, `ENABLE_OWNER_ROLE`, `ENABLE_PLATFORM_ROUTES` all false in prod.
- **Two parallel Stripe Connect onboarding paths** (OAuth vs Accounts-v2 hosted) — pick one before more academies onboard.
- **`_NullPlatformRoleRepository`** in `backend/v2/main.py` appears dead (both branches use the Mongo adapter) — delete-candidate.
- **Duplicate `app.state.bootstrap_academy` assignment** in `_lifespan` (main.py ~:186 and ~:523) — dead duplicate.
- **`_session_amount_cents` defaults to 2500 cents** when no price field is found (`backend/v2/composition/parent.py:1634`) — a silent magic price; make it fail loudly.
- **Registered no-op event handler** `on_student_placed_in_level`.
- **`.worktrees/autopay-optin` + three `.claude/worktrees/*`** — in-flight parallel branches; check them before assuming main has everything.
- **Quarantined Stripe events require manual replay** — no alerting loop beyond admin billing-health; check `stripe_webhook_events` for stuck `quarantined` rows periodically.
- **No scheduled *initial* autopay charge on fresh invoices** — dunning only retries already-attempted ones; the monthly invoice→charge automation is a roadmap item, not shipped.

### 22. Docs sprawl
- **What:** ~290 markdown files under `docs/`; stale cutover docs (`docs/cutover-w4-decommission.md`) describe a migration already completed; multiple overlapping plan/requirement generations.
- **Fix (single task):** Add a `docs/README.md` index marking authoritative docs (security-matrix, adr/, agent/, testing.md, runbooks/) vs. historical; move dead cutover docs to `docs/archive/`.
