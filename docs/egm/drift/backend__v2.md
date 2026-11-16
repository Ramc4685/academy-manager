## backend/v2/README.md

- [contract] README:103 says pytest runs with ">=70% coverage on `v2/shared`". CI enforces `--cov=v2 --cov-fail-under=86` over all of v2 (`.github/workflows/production.yml:165`).
- [contract] README:101 says mypy is `mypy --config-file backend/pyproject.toml v2`, advisory. CI runs `mypy --config-file backend/pyproject.toml -p backend.v2` filtered through `mypy-baseline` (`production.yml:273-274`), so new errors fail the build.
- [wording] README:98-103 CI list omits `ruff format --check` (`production.yml:264`) and the contract job (`production.yml:227`).
- [stale-not-built] README:3 links `../../../.claude/plans/write-a-detailed-plan-curried-trinket.md`. That path does not exist from the worktree (`.claude/plans` is absent).
- [contract] README:30 and README:53 call `main.py` the composition root and say to wire contexts there. Wiring lives in `backend/v2/composition/*.py` (e.g. `composition/admin.py`, `composition/pathway.py`). `main.py:31-33` only imports `compose_*` and mounts routers. `tests/structural/test_composition_is_wiring.py` targets `composition/admin.py`.
- [undocumented] README:10-31 Layout omits the `composition/` package.
- [undocumented] README:13 lists personas "admin, coach, parent, platform". Code also has `interfaces/owner/`, `interfaces/student/`, `interfaces/public/`, and top-level route modules (`me_routes.py`, `registration_routes.py`, `magic_link_routes.py`, `password_reset_routes.py`, `unsubscribe_routes.py`, `email_webhook_routes.py`).
- [undocumented] README:15-21 `shared/` list omits `comms/`, `profile/`, `scheduling/`, `security/`, `time/` and the top-level modules `caching.py`, `ids.py`, `money.py`, `names.py`, `occurrences.py`. `shared/auth/` also holds `staff_tiers.py`.
- [undocumented] README:24-29 `tests/` list omits `composition/`, `contexts/`, `fixtures/`, `infrastructure/`, `seed/`, `shared/`, plus `test_no_raw_tenant_mongo_access.py` and `test_pytest_timeout_backstop.py`.
- [undocumented] README:23 `scripts/` lists only `replay_event.py`. `scripts/reconcile_membership_roles.py` also exists.
- [stale-not-built] README:63 says to return a view DTO from `interfaces/<persona>/views.py`. `interfaces/owner/` and `interfaces/platform/` have no `views.py`. Admin has several `*_views.py` files.
- [wording] README:48 says to put domain events in `domain/events.py`. The identity context, named README:55 as the canonical example, has no `domain/events.py` or `domain/errors.py` (it has `domain/models.py` and `application/errors.py`). It has no `infrastructure/` mention either, only `domain/models.py` as the models file.
- [wording] README:42 "six layer rules" and README:33 "enforced by import-linter": ADR-0005 line 125 still has the import-linter task unchecked. The contracts do exist in `backend/pyproject.toml:83+`.
- [undocumented] README:22 `migrations/` describes boot migrations only. There are many numbered migrations, and two share a number (`0070_*`, `0145_*`), so README step 6 gives no numbering convention.
