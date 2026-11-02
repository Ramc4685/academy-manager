# parent-header-phone-fit

PR: #1107

## What changed
The parent app's top bar no longer runs off a phone screen when the academy has a logo and a long name. Before, the calendar, messages, profile and log-out icons were pushed about 39px past a 412px-wide phone, so every parent page scrolled sideways. Now the academy name truncates first. When the persona switcher also shows (a parent who is also a coach or admin), the icons drop to a second row instead of overlapping the name. The logo always keeps its full size.

## Deploy notes
Frontend only. No migration, no job, no config.

## Risk / rollback
Layout-only change to the parent shell header. If it misbehaves, revert this PR; no data is touched.
