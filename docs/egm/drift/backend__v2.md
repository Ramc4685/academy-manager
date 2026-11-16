## backend/v2/README.md

- [stale-not-built] README:3 links `../../../.claude/plans/write-a-detailed-plan-curried-trinket.md`; the file does not exist at that path (nor under `~/.claude/plans`).
- [stale-not-built] README:27 says contract tests run "mongo + stripe via testcontainers"; `backend/v2/tests/contract/` has no testcontainers usage, and CI runs the tier against a native mongod (`.github/workflows/production.yml:227`, job `backend-contract-real-mongo`).
- [contract] README:101 says `mypy --config-file backend/pyproject.toml v2` is "advisory"; CI runs `mypy --config-file backend/pyproject.toml -p backend.v2` piped through `mypy-baseline filter --baseline-path backend/mypy-baseline.txt` (`production.yml:268-274`), so new errors fail the build.
- [contract] README:103 says "≥70% coverage on `v2/shared`"; CI measures `--cov=v2` (whole package) with `--cov-fail-under=86` (`production.yml:165`).
- [wording] README:59 lists personas `coach, parent, admin` for BFF routes; `backend/v2/interfaces/` also has `owner/`, `platform/`, `public/` and `student/`. Of these, only `student/` has a `views.py` (README:63 step 5), while `platform/`, `owner/` and `public/` have none (`public/dtos.py` is used instead).
- [wording] README:30 labels `main.py` the "composition root"; wiring is split into `backend/v2/composition/` (about 90 modules, e.g. `account_deletion.py`) and `main.py:659` `_lifespan`. README:53 ("Wire the context into the composition root in `main.py`") omits `composition/`.
- [undocumented] The Layout block (README:10-30) omits `backend/v2/composition/`, the top-level route modules in `interfaces/` (`magic_link_routes.py`, `me_routes.py`, `password_reset_routes.py`, `registration_routes.py`, `email_webhook_routes.py`, `unsubscribe_routes.py`), and `interfaces/owner|public|student`.
- [undocumented] `shared/` subpackages `comms/`, `profile/`, `scheduling/`, `security/`, `time/`, and the top-level modules `caching.py`, `ids.py`, `money.py`, `names.py`, `occurrences.py` are not listed (README:14-21).
- [undocumented] Test directories `tests/composition`, `tests/contexts`, `tests/infrastructure`, `tests/shared`, `tests/seed`, `tests/fixtures` are not listed (README:24-29). The structural tier also holds many policy tests beyond layering and event rules (e.g. `test_openapi_snapshot.py`, `test_no_duplicate_routes.py`).
- [undocumented] `scripts/` also contains `reconcile_membership_roles.py` (README:23 names only `replay_event.py` as an example, so this is minor).

Re-checked 2026-11-16 (L8 PR #1181 return-audit fix): all 12 prior items re-verified and still hold; none fixed, no new divergences.
