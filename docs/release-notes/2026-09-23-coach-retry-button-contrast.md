# Coach Retry button contrast (UI-6)

PR: #942

## What changed
Every coach Retry button (Today, teaching plan, Sessions, skill updates, Calendar, skill passport, Needs-review tray) now uses one shared `RetryButton`: white on rally-cobalt-700 (6.70:1). The tray Retry was white on amber-600 (3.2:1), which failed WCAG AA.

## Deploy notes
No migrations and no owner steps. A standard frontend deploy is enough.

## Risk / rollback
Visual-only frontend change with no API, data or behaviour change. To roll back, revert PR #942.
