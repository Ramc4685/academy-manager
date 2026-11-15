## backend/v2/README.md

- [stale-not-built] README:3 links the migration plan `../../../.claude/plans/write-a-detailed-plan-curried-trinket.md`; the target file does not exist.
- [contract] README:27 says `tests/contract/` runs "mongo + stripe via testcontainers"; no testcontainers usage exists. `backend/v2/tests/contract/conftest.py:1-25` uses a real mongod via `CONTRACT_TESTS_MONGO_URL` and falls back to `mongomock-motor`.
- [contract] README:103 says CI runs `pytest v2/tests` with ≥70% coverage on `v2/shared`; `.github/workflows/production.yml:165` enforces `--cov=v2 --cov-fail-under=86` on all of v2.
- [contract] README:101 says mypy is "advisory" and runs `mypy ... v2`; `production.yml:273-274` runs `mypy -p backend.v2` and filters through `backend/mypy-baseline.txt` (new errors fail the build).
- [contract] README:53 (and README:30 "main.py # composition root") says to wire a context in `main.py`; the wiring is in `backend/v2/composition/*.py` (`compose_*`), and `backend/v2/tests/structural/test_composition_is_wiring.py` plus the import-linter contract `composition-is-outermost` (`backend/pyproject.toml:182`) cover that package.
- [missing] README:9-30 Layout omits `backend/v2/composition/` (about 90 modules).
- [undocumented] README:13 lists personas "admin, coach, parent, platform"; `backend/v2/interfaces/` also has `owner/`, `student/`, `public/`, plus top-level route files (`me_routes.py`, `magic_link_routes.py`, `registration_routes.py`, `unsubscribe_routes.py`, `email_webhook_routes.py`). README:57 lists only coach/parent/admin.
- [undocumented] README:14-21 `shared/` lacks `comms/`, `profile/`, `scheduling/`, `security/`, `time/` and the top-level modules `caching.py`, `ids.py`, `money.py`, `names.py`, `occurrences.py` in `backend/v2/shared/`.
- [undocumented] README:24-30 `tests/` lacks `composition/`, `contexts/`, `infrastructure/`, `shared/`, `fixtures/`, `seed/`, and the top-level `test_no_raw_tenant_mongo_access.py` and `test_pytest_timeout_backstop.py`.
- [wording] README:48 step 3 says to add `domain/events.py` for every context; `backend/v2/contexts/identity/domain/` (named the "canonical example" at README:56) has `models.py` and `errors.py` but no `events.py`.
- [wording] README:23 gives scripts as "(e.g., replay_event.py)"; `backend/v2/scripts/` also has `reconcile_membership_roles.py`.
