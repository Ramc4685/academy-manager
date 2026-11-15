# Drift backlog

README-vs-code divergences found by EGM drift reports. Details with file:line are in `docs/egm/drift/`. Fix the README or the code, then delete the line.

## Repo root (`README.md`): 3 items, from `drift/_root.md`
- [undocumented] README:83-84 says `academy-next` owns `academy.courtmastr.com/*`; `frontend/wrangler.jsonc:18-25` also routes `*.courtmastr.com/*`.
- [undocumented] Deploy steps omit the `sentry-release` job in `production.yml`.
- [wording] Validate step undersells the job: it also runs real-Mongo contract tests, lint, the OpenAPI drift check, the Worker runtime smoke, real-auth E2E and scripts validation.

## `backend/v2/README.md`: 19 items, from `drift/backend__v2.md`
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
- [wording] README:12 and :46 omit the ai, communications, crm, curriculum, finance, onboarding, platform and student_progress contexts.

## `frontend/README.md`: 16 items, from `drift/frontend.md`
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

## `frontend/lib/api/README.md`: 7 items, from `drift/frontend__lib__api.md`
- [stale-not-built] README says `generated/` holds only `.gitkeep`; `v2.d.ts` and `openapi.snapshot.json` are committed.
- [stale-not-built] CI "Skipping drift check" path no longer exists; drift check is unconditional.
- [contract] `pnpm generate:api` reads the committed snapshot, not the running app; the pytest `UPDATE_OPENAPI_SNAPSHOT=1` step is omitted.
- [undocumented] `apiFetchBlob`, Sentry failure capture, BFF/X-Academy-Id headers, 20s timeout in `client.ts`.
- [undocumented] Eight `admin-*` modules, twelve top-level modules, six `v2/` modules not listed.
- [wording] "When generated types are reintroduced": they already are.
