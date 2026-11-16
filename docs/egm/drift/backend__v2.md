## backend/v2/README.md

- [stale-not-built] README:3 links `../../../.claude/plans/write-a-detailed-plan-curried-trinket.md`; no such file resolves from `backend/v2/` (nothing under `.claude/plans` at that relative path).
- [contract] README:103 says `pytest v2/tests` with >=70% coverage on `v2/shared`; CI measures `--cov=v2` (whole package) with `--cov-fail-under=86` (`.github/workflows/production.yml:165`).
- [contract] README:101 says `mypy --config-file backend/pyproject.toml v2` is advisory; CI runs `mypy ... -p backend.v2` piped through `mypy-baseline filter` against `backend/mypy-baseline.txt`, so new errors fail the build (`.github/workflows/production.yml:268-274`).
- [wording] README:100 lists only `ruff` lint; CI also runs `ruff format --check v2` (`.github/workflows/production.yml:260-264`).
- [undocumented] README:13 lists persona routes as admin, coach, parent, platform; `backend/v2/interfaces/` also has `owner/`, `public/`, `student/` plus top-level route files (`me_routes.py`, `magic_link_routes.py`, `registration_routes.py`, `password_reset_routes.py`, `unsubscribe_routes.py`, `email_webhook_routes.py`).
- [undocumented] README:10-30 layout omits `backend/v2/composition/` (about 90 wiring modules, e.g. `composition/admin.py`), although README:30 and step 8 (line 53) say `main.py` is the composition root.
- [undocumented] README:14-21 `shared/` list omits `comms/`, `profile/`, `scheduling/`, `security/`, `time/` and top-level `shared/{caching,ids,money,names,occurrences}.py`.
- [undocumented] README:24-29 test layout omits `tests/{composition,contexts,infrastructure,seed,shared,fixtures}/`. `tests/structural/` also holds many policy and wiring tests beyond layer and event rules (`test_persona_gate_is_called.py:1`).
- [wording] README:48 and README:55 name `domain/events.py` and call Identity the canonical example, but `backend/v2/contexts/identity/domain/` has no `events.py` (only `errors.py`, `models.py` and others). Also, `contexts/identity/application/` holds flat use-case modules alongside `use_cases/`, contrary to README:49.
- [wording] README:12 lists context examples "identity, enrollment, coaching, billing, etc."; `contexts/` also has ai, communications, crm, curriculum, finance, onboarding, platform and student_progress (the last four-plus are not mentioned, and `platform`, `crm`, `ai` and `onboarding` carry their own READMEs).
