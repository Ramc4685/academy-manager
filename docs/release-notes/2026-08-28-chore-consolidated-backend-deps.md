# chore-consolidated-backend-deps

PR: #TBD

## What changed
Supersedes the grouped Dependabot PR #459, which cannot merge as authored: two
of its 51 updates break the build. This lands the other 49 and deliberately
holds those two back.

### Majors included (7)
- bcrypt 4.1.3 → 5.0.0
- openai 2.53.0 → 3.3.1
- protobuf 6.33.5 → 7.36.0
- python-ulid 3.1.0 → 4.0.1
- rpds-py 0.30.0 → 2026.6.3 (project switched to calendar versioning)
- websockets 16.0 → 17.0.1
- zipp 3.23.1 → 4.1.0

Only two of those seven touch code we actually run, and both were smoke-tested
directly against the new versions:
- **python-ulid 4** backs `backend/v2/shared/ids.py`. `ULID()` and
  `ULID.from_bytes()` both still behave as before, and `stable_ulid()` remains
  deterministic.
- **bcrypt 5** is used only by `backend/scripts/seed_local.py` and
  `backend/scripts/import_blno.py`, via the stable `hashpw`/`gensalt` API, which
  is unchanged. `passlib` is still pinned but is imported nowhere, so the
  well-known passlib/bcrypt incompatibility is not reachable.
- **openai 3** and **websockets 17** are transitive-only; neither is imported
  anywhere in the codebase.

Also notable, though not majors: fastapi 0.139.2 → 0.141.1, starlette 1.3.1 →
1.6.0, stripe 15.4.0 → 15.5.1, firebase-admin 7.4.0 → 7.5.0, grpcio 1.80.0 →
1.83.0, APScheduler 3.11.2 → 3.11.3. motor and pymongo are unchanged.

### Deliberately held back (2)
- **`pydantic_core` stays at 2.46.4** (#459 proposed 2.48.0). `pydantic 2.13.4`
  depends on `pydantic-core==2.46.4` exactly, so bumping the transitive pin on
  its own makes the requirements set uninstallable:
  `ERROR: ResolutionImpossible`. `pydantic_core` should only ever move when
  `pydantic` itself moves.
- **`pytest-asyncio` stays at 1.3.0** (#459 proposed 1.4.0). 1.4.0 fails 13
  tests in `test_coach_skill_routes.py` and `test_parent_progress_routes.py`
  with `RuntimeError: There is no current event loop`. Those tests pass
  individually and pass file-by-file — they only fail under `-n auto`, because
  they call the deprecated `asyncio.get_event_loop()`, which 1.4.0 no longer
  auto-creates once a sibling test closes the loop in the same xdist worker.
  This is a latent bug in our tests rather than a defect in the library; fixing
  those call sites is worth its own change, after which 1.4.0 can land.

## Deploy notes
None. Dependency pins only; no schema, env, route, or config changes. The
standard backend (Fly) deploy picks up the new versions. Frontend is untouched.

## Risk / rollback
Moderate — this is a large batch containing seven major bumps — but the risk is
bounded by the fact that the majors are overwhelmingly transitive, and the two
that reach real code were exercised directly.

Verified with the versions actually installed, not merely pinned. The throwaway
Python 3.12.8 virtualenv (`backend/.venv-local`) — matching the
`python-version: "3.12"` in `.github/workflows/production.yml` — was installed
from these exact files; pip resolved with no conflicts and `pip list` confirms
bcrypt 5.0.0, protobuf 7.36.0, python-ulid 4.0.1, rpds-py 2026.6.3,
websockets 17.0.1, zipp 4.1.0, openai 3.3.1, fastapi 0.141.1, starlette 1.6.0,
stripe 15.5.1, alongside the two held pins at pydantic_core 2.46.4 and
pytest-asyncio 1.3.0. Against that environment the full backend suite
`pytest v2/tests -n auto -q`, run from `backend/`, reports **3010 passed,
0 failed**. (An earlier run of the same pin set on an older `main` reported
2926 passed; the difference is tests added to `main` since, not skipped tests.)

To roll back, revert this commit to restore the prior pins.
