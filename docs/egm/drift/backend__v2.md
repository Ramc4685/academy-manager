## backend/v2/README.md

- [stale-not-built] README:3 links `../../../.claude/plans/write-a-detailed-plan-curried-trinket.md`; the target does not exist (resolves outside the repo, file absent).
- [stale-not-built] README:55 says the Identity context "is the canonical example", but `backend/v2/contexts/identity/domain/` has no `events.py`, which README:48 requires (other contexts have it, e.g. `contexts/billing/domain/events.py`).
- [contract] README:103 says pytest runs with ">=70% coverage on `v2/shared`"; CI runs `--cov=v2 --cov-fail-under=86` over all of v2 (`.github/workflows/production.yml:165`).
- [contract] README:101 calls mypy "advisory" and gives `mypy --config-file backend/pyproject.toml v2`; CI runs `-p backend.v2` filtered through `mypy-baseline`, so new errors fail the build (`production.yml:273-274`).
- [contract] README:33-40 and 42 show three layers and "six layer rules"; `backend/pyproject.toml:182` adds a `composition-is-outermost` contract. Only `interfaces` and `main` may import `backend/v2/composition/`. The layer diagram omits it.
- [undocumented] README:8-31 Layout omits `composition/` (~90 modules, the wiring layer). It also omits `shared/{comms,profile,scheduling,security,time}/` and the top-level `shared/*.py` helpers (`caching`, `ids`, `money`, `names`, `occurrences`).
- [undocumented] README:13 and 59 list interfaces `admin`, `coach`, `parent`, `platform`. Code also has `interfaces/owner/`, `interfaces/student/` (with `views.py`) and `interfaces/public/`. It also has top-level route modules: `me_routes.py`, `registration_routes.py`, `magic_link_routes.py`, `password_reset_routes.py`, `unsubscribe_routes.py`, `email_webhook_routes.py`.
- [undocumented] README:24-29 Layout omits test dirs `tests/composition`, `tests/contexts`, `tests/infrastructure`, `tests/shared`, `tests/seed`, `tests/fixtures`. It also omits `tests/test_no_raw_tenant_mongo_access.py` and `tests/test_pytest_timeout_backstop.py`.
- [undocumented] README:11 lists contexts "identity, enrollment, coaching, billing, etc." Code also has `ai`, `communications`, `crm`, `curriculum`, `finance`, `onboarding`, `platform`, `student_progress`.
- [undocumented] README:22-23 Layout does not mention `migrations/runner.py`, `migrations/cli.py` or `migrations/__main__.py`. It also omits `scripts/reconcile_membership_roles.py`.
- [wording] README:59 "Decide the persona - `interfaces/{coach,parent,admin}/`" is incomplete. Owner, student, platform and public personas also exist (`backend/v2/interfaces/`).
- [wording] README:96-98 CI list omits `ruff format --check` (`production.yml:264`), the contract job (`production.yml:227`) and the compile step.
