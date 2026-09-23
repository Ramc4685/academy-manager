# coach-retry-button-contrast

PR: #TBD

## What changed
Every coach Retry button (Today, teaching plan, Sessions, skill updates, Calendar, skill passport, Needs-review tray) now renders one shared `RetryButton`: white on rally-cobalt-700 (6.70:1). The tray Retry was white on amber-600 (3.2:1, failed WCAG AA).

## Deploy notes
none

## Risk / rollback
Visual-only frontend change; no API, data or behaviour change. Roll back by reverting the PR.
