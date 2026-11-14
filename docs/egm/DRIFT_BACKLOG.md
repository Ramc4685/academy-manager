# Drift backlog

README-vs-code divergences found by EGM drift reports. Details with file:line are in `docs/egm/drift/`. Fix the README or the code, then delete the line.

## Repo root (`README.md`): 3 items, from `drift/_root.md`
- [stale-not-built] `edge/` Worker router listed but the directory is gone.
- [stale-not-built] Pipeline step 6 `deploy-*` GitHub Release has no job in `production.yml`.
- [contract] README says Next.js 15; `frontend/package.json` pins 16.4.1.

## `backend/v2/README.md`: 15 items, from `drift/backend__v2.md`
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
- [wording] 5 wording items (shared/http middleware, persona list, admin router prefix, identity context shape); see report.

## `frontend/README.md`: 12 items, from `drift/frontend.md`
- [stale-not-built] `components/ui/` does not exist.
- [stale-not-built] `public/splash/` (and the 180 icon) do not exist.
- [stale-not-built] No workflow runs size-limit or lhci.
- [contract] README says Next.js 15; package pins 16.4.1.
- [undocumented] Route groups `(owner)`, `(platform)`, `(shared)`, `(student)`.
- [undocumented] Many `components/` and `lib/` folders.
- [undocumented] Capacitor, Sentry, Cloudflare/OpenNext, and test scripts.
- [undocumented] (see report for the fourth item)
- [wording] OpenAPI snapshot is committed (`lib/api/generated/v2.d.ts`, `openapi.snapshot.json`); README contradicts itself at line 88.
- [wording] Radix and `firebase/auth` usage overstated.
- [wording] Calendar dynamic imports live in page files, not the admin shell.
- [wording] (see report for the fourth item)
