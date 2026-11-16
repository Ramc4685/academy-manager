## backend/v2/README.md

- [stale-not-built] README:3 links `../../../.claude/plans/write-a-detailed-plan-curried-trinket.md`; the target does not exist from `backend/v2/` (it resolves outside the repo, and `~/.claude/plans/` has no such file).
- [contract] README:103 says `pytest v2/tests` runs with ">=70% coverage on `v2/shared`". `.github/workflows/production.yml:165` runs `--cov=v2 ... --cov-fail-under=86`, so the scope is all of `v2` and the threshold is 86.
- [contract] README:101 says mypy is "advisory". `.github/workflows/production.yml:273-274` runs `mypy -p backend.v2` through `mypy-baseline filter --baseline-path backend/mypy-baseline.txt`. Only new errors fail the build, so the check is a ratcheting gate rather than advisory. The command shape also differs: README says `mypy --config-file backend/pyproject.toml v2`, CI says `-p backend.v2`.
- [wording] README:12-30 Layout is incomplete.
  - `backend/v2/composition/` (about 70 `compose_*` modules, wired from `main.py`) is missing from the tree, and README:30 calls `main.py` the composition root.
  - `interfaces/` also has `owner/`, `student/` and `public/`, plus top-level route files (`me_routes.py`, `registration_routes.py`, `magic_link_routes.py` and others). README:13 lists only admin, coach, parent and platform.
  - `shared/` also has `comms/`, `profile/`, `scheduling/`, `security/`, `time/`, and `caching.py`, `ids.py`, `money.py`, `names.py` and `occurrences.py`.
  - `tests/` also has `composition/`, `contexts/`, `infrastructure/`, `shared/`, `fixtures/`, `seed/`, `test_no_raw_tenant_mongo_access.py` and others.
- [wording] README:12 names the contexts "identity, enrollment, coaching, billing, etc." The real set is ai, billing, coaching, communications, crm, curriculum, enrollment, finance, identity, onboarding, platform and student_progress (`backend/v2/contexts/`).
- [contract] README:48-49 and README:55 say every context has `domain/events.py`, `domain/errors.py`, `domain/models.py` and `application/ports.py`, and that Identity is the canonical example.
  - `contexts/identity/domain/` has `errors.py` and `models.py` but no `events.py`. It is also missing for ai, communications, crm, finance and platform.
  - `contexts/finance/domain/` has neither `errors.py` nor `models.py`.
- [contract] README:59 gives the persona choice as `interfaces/{coach,parent,admin}/`. The code also has `interfaces/owner`, `student`, `platform` and `public` (`backend/v2/main.py:3069-3081`). README:13 lists platform but not owner, student or public.
- [contract] README:63 says each persona has `interfaces/<persona>/views.py`. `interfaces/owner/` and `interfaces/public/` have no `views.py`, and `interfaces/admin/` also has `collections_views.py`, `families_views.py`, `family_index_views.py` and `month_close_views.py`.
- [wording] README:61 says the persona-prefix path is `/api/v2/<persona>/<resource>`. `backend/v2/main.py:3062-3069` also mounts non-persona routers under `/api/v2` (me, registration, magic-link, password-reset, unsubscribe, email-webhook, public), and `/api/v2/healthz` at `main.py:3041`.
- [undocumented] `shared/tenancy/README.md` and scripts other than `replay_event.py` exist (`backend/v2/scripts/reconcile_membership_roles.py`). README:23 gives `replay_event.py` only as an "e.g.", so this is minor.
