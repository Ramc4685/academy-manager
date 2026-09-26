# Unsaved-changes guard catches a leave that follows a keystroke closely

PR: #TBD

## What changed
- The admin shell's unsaved-changes guard (`components/admin/unsaved-changes-guard.tsx`) now records a surface's dirty state at the moment the surface reports it, in a ref written by `setUnsaved`. Before, `requestLeave` and the link listener read a ref that an effect synced from React state, which caught up a render after the keystroke. A student tab switch (Enter or click) or an in-app link click that landed inside that window left with no dialog and silently dropped the typed edit. The in-app link listener is now always attached and checks the same ref.
- This was the "student detail warns before a tab switch" flake on the Nightly E2E WebKit job. The spec now has a deterministic same-tick step (type and click the tab in one `evaluate`). It fails every time on the old guard, on both chromium and webkit.

## Deploy notes
- Frontend only. No migration, no env vars.

## Risk / rollback
- Low. The same guard, dialog and copy. Only when it reads the dirty state changes. It covers the student, user, family details and Settings surfaces. The guard specs pass 10x on webkit-mobile, chromium-mobile and chromium-desktop.
- Rollback: revert this PR.
