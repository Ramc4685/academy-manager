## backend/v2/README.md

- [stale-not-built] README:3 links `../../../.claude/plans/write-a-detailed-plan-curried-trinket.md`; the file does not exist at that path (nor under `~/.claude/plans`).
- [contract] README:27 says `contract/` runs "mongo + stripe via testcontainers". `backend/v2/tests/contract/conftest.py:1-8` uses a real mongod from `CONTRACT_TESTS_MONGO_URL` (CI native mongod 8.0) with a `mongomock-motor` fallback. No testcontainers usage exists.
- [contract] README:103 says `pytest v2/tests` with >=70% coverage on `v2/shared`. `.github/workflows/production.yml:165` uses `--cov=v2 --cov-fail-under=86` over all of v2.
- [contract] README:101 calls mypy "advisory" with `... v2`. `production.yml:273-274` runs `mypy -p backend.v2` filtered against `backend/mypy-baseline.txt`; new errors fail the build.
- [contract] README:102 (and :33) say import-linter enforces "layer rules + tenancy". `backend/pyproject.toml:190-193` says the tenancy `academy_id` literal rule is a pytest check (`tests/structural/test_tenancy_literals.py`), and `:170` says the cross-context rule is a structural test too. README:42 "six layer rules" is the ADR's count, not the linter's.
- [missing] README:48 requires `domain/events.py` per context, but `contexts/identity/domain/` has no `events.py`. README:55 names Identity as the canonical example. Same gap likely in `ai`, `communications`, `crm`, `finance`, `platform`.
- [missing] README:63 says views live in `interfaces/<persona>/views.py`. `views.py` exists only for admin, coach, parent and student (`backend/v2/interfaces/*/views.py`); platform and owner have none.
- [undocumented] README:11-30 and :35-40 omit `backend/v2/composition/` (91 wiring modules), the outermost layer (`backend/pyproject.toml:182`). README:53 says to wire a context "in `main.py`", but wiring lives in `composition/*.py`.
- [undocumented] README:13 and :59 list personas admin, coach, parent, platform. Code also has `interfaces/owner`, `interfaces/student`, `interfaces/public` and top-level `me_routes.py`, `registration_routes.py`, `magic_link_routes.py`, `unsubscribe_routes.py`, `email_webhook_routes.py` (`backend/v2/main.py:2892-2910`).
- [undocumented] README:14-21 `shared/` omits `comms/`, `profile/`, `scheduling/`, `security/`, `time/` and top-level `caching.py`, `ids.py`, `money.py`, `names.py`, `occurrences.py`. `http/` and `observability/` also hold more than the README's descriptions say (`rate_limit.py`, `persona.py`, `ops_digest.py`, etc.).
- [undocumented] README:12 omits contexts `ai`, `communications`, `crm`, `curriculum`, `finance`, `onboarding`, `platform`, `student_progress` (`backend/v2/contexts/`).
- [undocumented] README:24-29 test layout omits `tests/composition`, `tests/contexts`, `tests/infrastructure`, `tests/shared`, `tests/seed`, `tests/fixtures`; `tests/structural` holds many policy tests beyond "layer-conformance + event-rules".
- [wording] README:5 and :93 say all routes mount under `/api/v2/*`; true, but platform, student and owner routers are conditional on `enable_platform_routes`, `enable_student_login`, `enable_owner_role` (`main.py:2899-2910`).
- [wording] README:46 says each context has `{domain,application,infrastructure}`; `curriculum/` also has `content/` and some contexts nest subcontexts.
- [wording] README:36-40 diagram shows interfaces -> application -> domain. The linter (`backend/pyproject.toml:128-142`) lets interfaces import application only, not domain directly, but transitive imports are allowed. README:42 says "six layer rules" while pyproject has Rules 1-7 plus 4b.

Re-checked 2026-11-16 against the coach-attendance change (fix/coach-attendance, incl. review fix round): no new drift; items above still hold.
