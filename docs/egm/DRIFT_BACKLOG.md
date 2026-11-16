# Drift backlog

README-vs-code divergences found by EGM drift reports. Details with file:line are in `docs/egm/drift/`. Fix the README or the code, then delete the line.

## Repo root (`README.md`): 11 items, from `drift/_root.md`
- [undocumented] README:83-84 says `academy-next` owns `academy.courtmastr.com/*`; `frontend/wrangler.jsonc:18-25` also routes `*.courtmastr.com/*`.
- [undocumented] Deploy steps omit the `sentry-release` job in `production.yml`.
- [wording] README:98 shows `flyctl deploy --remote-only`; production.yml deploys a prebuilt `--image` with `--ha=false`.
- [wording] Validate step undersells the job: it also runs real-Mongo contract tests, lint, the OpenAPI drift check, the Worker runtime smoke, real-auth E2E and scripts validation.
- [wording] README:173 lists importers under `scripts/`; none exist there.
- [wording] README:51 says multi-region; the API runs one machine in one region (`backend/fly.toml:2`).
- [wording] Auth methods: README:31,142 name only Google and email/password; code also has Apple and magic links, and self-registration is email/password only.
- [wording] README:101-102 says the release record publishes only when every changed component deployed; `publish-release` gates only on smoke succeeding on `main` (`production.yml:1126-1129`).
- [wording] README:116-117 says email verification is checked on every authenticated request; only the per-provider rule in `token_claims.py:19-36` was confirmed.
- [wording] README:139 gives a `SECURITY DISCLOSURE` subject line; `SECURITY.md` has no matching contact.
- [wording] Email verification is required for every provider except magic-link custom tokens (`token_claims.py:25-48`).

## `backend/v2/README.md`: 25 items, from `drift/backend__v2.md`
- [stale-not-built] Migration-plan link under `.claude/plans/` is dead.
- [contract] Coverage: README ≥70% on `v2/shared`; CI enforces 86% on all of `v2`.
- [contract] Mypy "advisory"; CI fails new errors via the baseline filter.
- [contract] Import-linter list omits `invoicing-core-independent-of-academy-pricing` and `composition-is-outermost`.
- [contract] Contract tests: README says testcontainers; conftest uses `CONTRACT_TESTS_MONGO_URL` mongod / mongomock.
- [undocumented] `composition/` missing from Layout (README says wiring lives in `main.py`).
- [undocumented] `shared/` subpackages missing from Layout.
- [undocumented] `interfaces/` route modules and `scripts/reconcile_membership_roles.py` missing from Layout.
- [undocumented] Test directories missing from the tests list.
- [undocumented] Boot migrations gated by `run_migrations_on_boot`, and the context list, are not described.
- [undocumented] CI section omits `ruff format --check` and the real-Mongo contract job.
- [undocumented] Top-level test files (`test_pytest_timeout_backstop.py`, `_route_paths.py`, `conftest.py`) missing from tests layout.
- [contract] `pyproject.toml` cites missing `tests/structural/test_tenancy_literals.py`; tenancy check is `tests/test_no_raw_tenant_mongo_access.py`.
- [wording] Persona list, admin router prefix (`interfaces/admin/router.py:61`), identity context shape, `views.py` not in every persona; see report.
- [wording] README:69 says run from the repo root; CI runs from `backend/`.
- [contract] README:42 says import-linter enforces six layer rules; `pyproject.toml` has five forbidden contracts plus `composition-is-outermost`, and the no-cross-context and tenancy rules are pytest checks.
- [wording] README:49 places `ports.py` as a sibling of `use_cases/` under `application/`; minor.
- [wording] README mypy command differs from CI's baseline-filter invocation.
- [wording] README:12 and :46 omit the ai, communications, crm, curriculum, finance, onboarding, platform and student_progress contexts.

- [wording] README cites W1A-02 (nowhere in code); migrations dir has two `0070_*` files despite "one file per index set".

- [missing] Identity (the canonical example) and several other contexts have no `domain/events.py`.
- [contract] README:46,49 describe `application/use_cases/`; identity (the canonical example, README:55) keeps most use cases directly in `application/`.
- [wording] Platform, student and owner routers mount behind settings flags, not always under `/api/v2`.

## `frontend/README.md`: 18 items, from `drift/frontend.md`
- [stale-not-built] `components/ui/` does not exist.
- [stale-not-built] `public/splash/` (and the 180 icon) do not exist.
- [stale-not-built] No workflow runs size-limit or lhci.
- [contract] README says Next.js 15; package pins 16.4.6.
- [undocumented] Route groups `(owner)`, `(platform)`, `(shared)`, `(student)`.
- [undocumented] Many `components/` and `lib/` folders.
- [undocumented] Capacitor, Sentry, Cloudflare/OpenNext, and test scripts.
- [wording] OpenAPI snapshot is committed (`lib/api/generated/v2.d.ts`, `openapi.snapshot.json`); README contradicts itself at line 88.
- [wording] Radix and `firebase/auth` usage overstated.
- [wording] Calendar dynamic imports live in page files, not the admin shell.
- [stale-not-built] `components/coach` is not dynamically imported (static in coach layout).
- [undocumented] Layout omits `middleware.ts`, `app/sw.ts`, CSP report and v2 proxy routes, Dockerfile, `e2e/`, `scripts/`.
- [undocumented] Three more no-patch GHSA exceptions in `pnpm-workspace.yaml`.
- [undocumented] Audit runs via `scripts/ci/dependency_audit.sh` (soft-fails on unreachable registry).
- [wording] Public landing is `app/page.tsx`, not under `(marketing)`.
- [wording] `pnpm typecheck` runs `next typegen && tsc --noEmit`.
- [wording] README:84-86 omit that `build` runs `--webpack` and `dev` honors `$PORT`.
- [wording] README:23 mentions coach teaching-plan flows; no such route under `app/(coach)/coach/`.

## `frontend/lib/api/README.md`: 10 items, from `drift/frontend__lib__api.md`
- [undocumented] README calls `admin.ts` a thin wrapper; `chargeAdminInvoiceAutopay` keeps per-invoice retry state (reused `request_id` for 10 min; kept on 409 only for `charge_in_progress`).
- [stale-not-built] README says `generated/` holds only `.gitkeep`; `v2.d.ts` and `openapi.snapshot.json` are committed.
- [stale-not-built] CI "Skipping drift check" path no longer exists; drift check is unconditional.
- [contract] `pnpm generate:api` reads the committed snapshot, not the running app; the pytest `UPDATE_OPENAPI_SNAPSHOT=1` step is omitted.
- [undocumented] `apiFetchBlob`, Sentry failure capture, BFF/X-Academy-Id headers, 20s timeout in `client.ts`.
- [undocumented] Eight `admin-*` modules, twelve top-level modules, six `v2/` modules not listed.
- [wording] "When generated types are reintroduced": they already are.
- [wording] README says every request is deduplicated; `client.ts:195` dedups only when `dedup` is set or the request is a read.
- [undocumented] `password-reset.ts` (from #1180) is not in the README's wrapper list.

## `backend/v2/contexts/crm/README.md`: 7 items, from `drift/backend__v2__contexts__crm.md`
- [wording] README:17-20 says the context ships no route or wiring; staff pipeline routes and `composition/crm_pipeline.py` exist.
- [missing] Record table omits `attribution`, `owner_alert_due_at`, `owner_alert_sent_at` and `acknowledged_at`.
- [undocumented] `SubmitWebsiteInquiry` / `WebsiteInquiryResult` / `RepeatInquiryWriter` missing from the Layout table.
- [undocumented] `clean_attribution`, `ATTRIBUTION_FIELDS`, `MAX_ATTRIBUTION_LEN`, `REPEAT_INQUIRY_AFTER` and first-touch attribution rules not in the README.
- [undocumented] `send_pipeline_reply.py` (`SendPipelineReply`) has no Layout row or contract.
- [undocumented] Family contacts (use cases, domain, repo, routes, composition) have no section.
- [undocumented] `infrastructure/mongo_family_erasure.py` is not mentioned.

## `backend/v2/contexts/onboarding/README.md`: 2 items, from `drift/backend__v2__contexts__onboarding.md`
- [undocumented] Applications, waiver templates and waiver signatures are in scope but only AI/video consent is documented.
- [undocumented] `ParentProfile.heard_from` (optional, max 80, `[A-Za-z0-9_.-]*`) is not mentioned.
