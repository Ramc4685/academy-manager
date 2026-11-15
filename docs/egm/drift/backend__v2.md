## backend/v2/README.md

- [wording] README:14-21 lists `shared/` subpackages but omits `comms/`, `profile/`, `scheduling/`, `security/`, `time/` and top-level modules (`caching.py`, `ids.py`, `money.py`, `names.py`, `occurrences.py`) present in `backend/v2/shared/`.
- [wording] README:13 says interfaces are "admin, coach, parent, platform"; `backend/v2/interfaces/` also has `owner/`, `student/`, `public/` plus top-level route files (`me_routes.py`, `registration_routes.py`, `magic_link_routes.py`, `email_webhook_routes.py`, `unsubscribe_routes.py`).
- [undocumented] README layout (lines 10-30) omits `backend/v2/composition/` (per-feature wiring modules, e.g. `composition/admin.py`); `tests/composition/`, `tests/contexts/`, `tests/infrastructure/`, `tests/shared/`, `tests/seed/`, `tests/fixtures/` are also missing from the tests list (README:24-29).
- [contract] README:53 says to wire a context into the composition root in `main.py`; wiring is split across `backend/v2/composition/*.py`, with `main.py` only calling it (`backend/v2/main.py:654` onward, enforced by `tests/structural/test_composition_is_wiring.py`).
- [contract] README:48 and :49 say every context has `domain/events.py` and `application/use_cases/` plus `application/ports.py`. The identity context, which README:55 calls canonical, has no `domain/events.py` (`contexts/identity/domain/`). Its use cases mostly sit flat in `application/*_use_case.py`, not in `use_cases/`.
- [contract] README:103 says pytest runs with ">=70% coverage on `v2/shared`". CI runs `--cov=v2 ... --cov-fail-under=86` over all of v2 (`.github/workflows/production.yml:165`).
- [contract] README:101 says mypy is "advisory". CI runs it blocking against a frozen baseline (`.github/workflows/production.yml:266-274`).
- [wording] README:101 gives `mypy --config-file backend/pyproject.toml v2`; CI runs `mypy --config-file backend/pyproject.toml -p backend.v2` (`production.yml:273`).
- [wording] README:97-103 CI list omits the contract-test job (`production.yml:227`), `ruff format --check` (`production.yml:264`) and other jobs.
- [wording] README:3 links the migration plan at `../../../.claude/plans/write-a-detailed-plan-curried-trinket.md`, which does not resolve in the repo (no `.claude/plans` directory at that path).
- [wording] README:23 gives `scripts/` as "operator CLIs (e.g., replay_event.py)"; it also contains `reconcile_membership_roles.py` (`backend/v2/scripts/`).
- [wording] README:12 context list "identity, enrollment, coaching, billing, etc." omits the `ai`, `communications`, `crm`, `curriculum`, `finance`, `onboarding`, `platform` and `student_progress` contexts (the "etc." covers it loosely).
