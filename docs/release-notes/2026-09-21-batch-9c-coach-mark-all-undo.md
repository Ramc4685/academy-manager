# batch-9c-coach-mark-all-undo

PR: #0

## What changed

- Fixes #846 — "Mark all present" on the coach roster used to commit on the tap: a bulk POST online, or an IndexedDB queue entry offline, so a courtside mis-tap was instantly a server fact (notifications sent, billing synced) and fixable only row by row. The batch is now held on the phone for 5 seconds behind a pinned bottom bar reading "Marked N present · Undo", and only then goes down the existing path — same payloads, idempotency keys, and #841 labels; no new endpoint and no change to the offline queue contract. Tapping Undo inside the window cancels the enqueue so nothing ever reaches the server. The timer elapsing, `pagehide`, `visibilitychange` going hidden, a replacement batch starting, or unmount on route change all flush the held batch immediately, so marks are never silently lost. Held rows are visibly pending (hollow dashed green, deliberately distinct from the solid #844 recorded-green) and their controls are frozen until the window closes. Single-row marks are unaffected — they keep today's immediate save and the #646 correct-mark path.
- Roster row layout: the stacked block (name + tags on one line, all four 44px controls on the next) is gone, slimming a row from ~116px to ~88px and fixing the desktop wrap that put a student's name underneath the Present button.

## Deploy notes

Frontend-only change (coach roster UI + client-side hold/flush timer). No new backend endpoint, no schema or migration changes, no change to the offline queue's IndexedDB contract. No new environment variables.

## Risk / rollback

Low. The change only delays when an already-existing bulk-mark request is sent (or cancels it before it is ever sent); it does not change what is sent, the idempotency keys used, or the offline queue's storage format. Single-mark flows are untouched. Full backend gate (pytest, ruff check/format, lint-imports, mypy-baseline) and frontend gate (tsc, eslint, `next build --webpack`) pass on the branch. To roll back, revert this PR's merge commit.
