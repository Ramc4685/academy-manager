## backend/v2/README.md

- [contract] README:103 says `pytest v2/tests` with >=70% coverage on `v2/shared`; CI runs `--cov=v2 ... --cov-fail-under=86` over all of v2 (`.github/workflows/production.yml:165`).
- [contract] README:101 says mypy is `mypy --config-file backend/pyproject.toml v2`, advisory; CI runs `mypy ... -p backend.v2` filtered through `mypy-baseline` so NEW errors fail the build (`.github/workflows/production.yml:268-274`).
- [undocumented] README:10-31 Layout omits `composition/` (about 90 wiring modules, `backend/v2/composition/*.py`), which holds most of the context wiring that README:53 says lives in `main.py`.
- [undocumented] README:13 lists persona BFFs "admin, coach, parent, platform"; code also has `interfaces/owner/`, `interfaces/student/`, `interfaces/public/` and top-level route modules (`me_routes.py`, `registration_routes.py`, `magic_link_routes.py`, ...). Mounted at `main.py:2928-2947`. Student, owner and platform routers are flag-gated.
- [undocumented] README:14-21 `shared/` omits `comms/`, `profile/`, `scheduling/`, `security/`, `time/` (`backend/v2/shared/`).
- [undocumented] README:24-29 `tests/` lists 5 subfolders; code also has `composition/`, `contexts/`, `infrastructure/`, `shared/`, `fixtures/`, `seed/` (`backend/v2/tests/`).
- [wording] README:53 "Wire the context into the composition root in `main.py`"; wiring is split across `composition/*.py` and `main.py` (e.g. `main.py:67`, `main.py:771`).
- [wording] README:12 lists contexts as "identity, enrollment, coaching, billing, etc."; the etc. includes `curriculum`, `crm`, `ai`, `finance`, `onboarding`, `platform`, `student_progress`, `communications`. Several contexts have no `domain/models.py`-style layout (e.g. `contexts/identity/domain/` has many modules, `contexts/curriculum/` has `content/`), so README:46-49 conventions are only loosely followed.
- [wording] README:61 "persona-prefix path (`/api/v2/<persona>/<resource>`)" does not cover the unprefixed routers mounted at `main.py:2928-2933`.
