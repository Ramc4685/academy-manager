## backend/v2/README.md

- [stale-not-built] README:3 links `../../../.claude/plans/write-a-detailed-plan-curried-trinket.md`; the file does not exist (not under `~/.claude/plans` either).
- [contract] README:27 says `contract/` runs "mongo + stripe via testcontainers". `backend/v2/tests/contract/conftest.py:1-8,36-40` uses a real mongod from `CONTRACT_TESTS_MONGO_URL` with a `mongomock-motor` fallback. No testcontainers.
- [contract] README:103 says `pytest v2/tests` with >=70% coverage on `v2/shared`. `.github/workflows/production.yml:165` uses `--cov=v2 --cov-fail-under=86` over all of v2.
- [contract] README:101 calls mypy "advisory" with `... v2`. `production.yml:272-274` runs `mypy -p backend.v2` filtered by `backend/mypy-baseline.txt`; new errors fail the build.
- [contract] README:102 and :33 say import-linter enforces "layer rules + tenancy". `backend/pyproject.toml:190-193` says the `academy_id` literal rule (Rule 6) is a pytest check, and `:177-180` says composition purity is a structural test (`tests/structural/test_composition_is_wiring.py`). README:42 "six layer rules" is the ADR's count; pyproject has Rules 1-7 plus 4b.
- [missing] README:48 requires `domain/events.py` per context. It is absent in `contexts/identity/domain/` (README:55 names Identity as the canonical example) and in `ai`, `communications`, `crm`, `finance`, `platform`.
- [missing] README:63 says views live in `interfaces/<persona>/views.py`. Only admin, coach, parent, student have `views.py` (`backend/v2/interfaces/*/views.py`); platform and owner do not.
- [undocumented] README:11-30 and :35-40 omit `backend/v2/composition/` (91 wiring modules), the outermost layer (`backend/pyproject.toml:173-188`). README:53 says to wire a context "in `main.py`"; wiring lives in `composition/*.py`, assembled from `main.py`.
- [undocumented] README:13 and :59 list personas admin, coach, parent, platform. Code also has `interfaces/owner`, `student`, `public` and top-level `me_routes.py`, `registration_routes.py`, `magic_link_routes.py`, `unsubscribe_routes.py`, `email_webhook_routes.py` (`backend/v2/main.py:2969-2987`).
- [undocumented] README:14-21 `shared/` omits `comms/`, `profile/`, `scheduling/`, `security/`, `time/` and top-level `caching.py`, `ids.py`, `money.py`, `names.py`, `occurrences.py`.
- [undocumented] README:12 omits contexts `ai`, `communications`, `crm`, `curriculum`, `finance`, `onboarding`, `platform`, `student_progress` (`backend/v2/contexts/`).
- [undocumented] README:24-29 test layout omits `tests/composition`, `tests/contexts`, `tests/infrastructure`, `tests/shared`, `tests/seed`, `tests/fixtures`; `tests/structural` holds many policy tests beyond "layer-conformance + event-rules".
- [wording] README:5 and :93 say all routes mount under `/api/v2/*`; true, but platform, student and owner routers are conditional on `enable_platform_routes`, `enable_student_login`, `enable_owner_role` (`main.py:2976-2987`).
- [wording] README:46 says each context has `{domain,application,infrastructure}`; `contexts/curriculum/` also has `content/`.
- [wording] README:36-40 diagram shows interfaces -> application -> domain; Rule 4 (`backend/pyproject.toml:128-142`) forbids interfaces importing domain directly, which the diagram implies only indirectly.
