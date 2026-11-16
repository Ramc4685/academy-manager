## backend/v2/README.md

- [stale-not-built] README:3 links `../../../.claude/plans/write-a-detailed-plan-curried-trinket.md`; the target does not exist (no `.claude/plans` dir above the worktree).
- [undocumented] README:13 lists personas "admin, coach, parent, platform"; code also mounts `interfaces/owner/` (router.py), `interfaces/student/` (views.py) and `interfaces/public/` (academy_page_routes.py), plus top-level route modules (`interfaces/me_routes.py`, `magic_link_routes.py`, `password_reset_routes.py`, `registration_routes.py`, `unsubscribe_routes.py`, `email_webhook_routes.py`). README:59 "coach,parent,admin" is likewise incomplete.
- [undocumented] README:10-31 Layout omits `composition/` (about 90 wiring modules, e.g. `composition/admin.py`, `composition/pathway.py`) and `shared/` subdirs `comms/`, `profile/`, `scheduling/`, `security/`, `time/` and files `caching.py`, `ids.py`, `money.py`, `names.py`, `occurrences.py`. The `main.py` comment "composition root" is only partly accurate.
- [contract] README:53 "Wire the context into the composition root in `main.py`" vs code: contexts are wired in `composition/<name>.py` (enforced by `tests/structural/test_composition_is_wiring.py`), and `main.py:2928` only includes routers.
- [contract] README:27 "contract/ — mongo + stripe via testcontainers" vs `tests/contract/conftest.py:87-98`: uses a real Mongo at `V2_MONGO_URL`/`MONGO_URL`/`127.0.0.1:27017`; no testcontainers usage found in tests.
- [contract] README:101 "mypy ... (advisory in the backend lint job)" vs `.github/workflows/production.yml:268-274`: mypy runs with `mypy-baseline filter`, so new errors fail the build. README:101 also shows `mypy ... v2`; CI runs `mypy -p backend.v2`.
- [contract] README:103 "≥70% coverage on `v2/shared`" vs `.github/workflows/production.yml:165`: `--cov=v2 --cov-fail-under=86` (whole v2 package).
- [wording] README:98-103 CI list omits the contract-test job (`production.yml:227`), `ruff format --check` (`production.yml:264`) and `compileall`; README:91 `.github/workflows/production.yml` is correct.
- [wording] README:48 says domain events go in `domain/events.py`, but only 6 of 12 contexts have that file (e.g. `contexts/identity/domain/` has none; the "canonical example" at README:55 does not follow the step).

- [wording] README:42 "six layer rules": `backend/pyproject.toml:83-188` has six import-linter contracts, but they are not the ADR-0005 six (they include `invoicing-core-independent-of-academy-pricing` and `composition-is-outermost`), and the tenancy rule 6 is a pytest check (pyproject:190-192).
