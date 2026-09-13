# Coach shell header overflow on phone

PR: #0

## What changed
- Fixes #745 — the coach shell header (`app/(coach)/layout.tsx`) was a single
  no-wrap flex row. An academy admin covering a session (back button +
  persona switcher visible) on a 390px phone already overflowed to 394px,
  and going offline (Offline chip) pushed it to 456px with Log out entirely
  off-screen. Both header clusters now wrap (`flex-wrap` + `gap-y-2`), the
  wordmark truncates instead of forcing width, and the right-hand cluster is
  pinned with `ml-auto` and wraps independently so Log out always stays
  on-screen.
- Added `frontend/e2e/specs/coach-shell-header.spec.ts`, which reproduces the
  admin-covering-a-session + offline scenario at 390x844 and asserts no
  document horizontal overflow and that the Log out button stays within the
  viewport, both online and offline.

## Deploy notes
No migrations. Frontend-only CSS/layout change; no manual steps or env vars
required.

## Risk / rollback
Low risk — layout-only change scoped to the coach shell header, with a new
e2e test covering the regression scenario. The existing safe-area top
padding (#647) is unchanged. If this regresses, revert this PR's merge
commit.
