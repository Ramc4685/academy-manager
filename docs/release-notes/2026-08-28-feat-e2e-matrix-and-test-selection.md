# e2e-matrix-and-test-selection

PR: #495

## What changed
Pull requests no longer run the secondary E2E browser suites (Chromium
Desktop, WebKit) unless `frontend/e2e/**` files changed — a new `e2e` output
on the Detect Changes filter gates them (#476). Chromium mobile and Real
Auth still run on every relevant PR, and every suite still runs on push to
main. The pre-push hook's backend-only tier now selects focused tests via
`scripts/dev/lib/select-backend-tests.sh` (#482): changed test files, the
mirrored `v2/tests/contexts/<name>` directory for changed context sources,
and test files importing a changed module's dotted path, falling back to the
structural suite when nothing maps; the hook prints its selection. The
committed hook test suite grows to 24 cases.

## Deploy notes
None. No application code. PR CI wall time should drop for frontend changes
(WebKit was the long pole); the full matrix still runs pre-deploy on main.

## Risk / rollback
A regression visible only in a secondary browser can now merge from a PR
that did not touch e2e files — it is caught on the main-push run, where
production-approval requires CI Gate success, so it can block deploys until
reverted rather than reaching production. If WebKit-only failures start
appearing on main, revert the two `if:` conditions in production.yml to
restore the full PR matrix. The focused-test selector only affects the local
hook; CI still runs the full 2,719-test suite on every PR.
