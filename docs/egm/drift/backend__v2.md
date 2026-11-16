## backend/v2/README.md

- [stale-not-built] README:3 links `../../../.claude/plans/write-a-detailed-plan-curried-trinket.md`. The file does not exist (checked the relative path and `~/.claude/plans`).
- [contract] README:27 says `contract/` runs "mongo + stripe via testcontainers". `backend/v2/tests/contract/conftest.py:1-8,36-40` uses a real mongod from `CONTRACT_TESTS_MONGO_URL` with a `mongomock-motor` fallback. It does not use testcontainers.
- [contract] README:103 says `pytest v2/tests` with >=70% coverage on `v2/shared`. `.github/workflows/production.yml:165` runs `--cov=v2 --cov-fail-under=86`, which covers all of v2.
- [contract] README:101 says mypy is `mypy --config-file backend/pyproject.toml v2`, advisory. `.github/workflows/production.yml:268-274` runs `mypy -p backend.v2` through `mypy-baseline filter`. New errors fail the build, so it is not advisory.
- [undocumented] README:12-14 (Layout) omits `backend/v2/composition/` (about 90 composition modules, wired from `main.py`).
- [undocumented] README:12-14 (Layout) omits the `interfaces/owner`, `interfaces/student` and `interfaces/public` persona packages and the top-level route modules (`me_routes.py`, `registration_routes.py`, `magic_link_routes.py`, `unsubscribe_routes.py`, `email_webhook_routes.py`). README:13 and README:59 list only admin, coach, parent and platform. `backend/v2/main.py:2969-2987` mounts all of them.
- [undocumented] README:14-21 (Layout) omits `shared/comms`, `shared/profile`, `shared/scheduling`, `shared/security` and `shared/time`. It also omits the top-level `shared/{caching,ids,money,names,occurrences}.py`.
- [undocumented] README:22 omits the migration runner (`backend/v2/migrations/{__main__,cli,runner}.py`, run as `python -m backend.v2.migrations` from `backend/fly.toml:47`).
- [undocumented] README:24-29 (tests) omits `tests/{composition,contexts,infrastructure,shared,fixtures,seed}/`. It also omits top-level guard tests such as `test_no_raw_tenant_mongo_access.py`.
- [wording] README:23 gives `replay_event.py` as the example operator CLI. `backend/v2/scripts/` also holds `reconcile_membership_roles.py`.
- [wording] README:12 lists the contexts as "identity, enrollment, coaching, billing, etc.". `backend/v2/contexts/` has 12 contexts (ai, billing, coaching, communications, crm, curriculum, enrollment, finance, identity, onboarding, platform, student_progress). Five of them have their own READMEs.
- [contract] README:63 says to return a view DTO from `interfaces/<persona>/views.py`. `interfaces/owner/`, `interfaces/platform/` and `interfaces/public/` have no `views.py`. Only admin, coach, parent and student do.
- [contract] README:48 and README:55 say each context has `domain/events.py` and that Identity is the canonical example. `backend/v2/contexts/identity/domain/` has no `events.py` (it has `errors.py` and `models.py`). Identity's `application/` also keeps many `*_use_case.py` modules beside `use_cases/`.
