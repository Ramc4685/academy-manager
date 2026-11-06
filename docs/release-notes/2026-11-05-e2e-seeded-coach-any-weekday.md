# Real-backend journeys find the seeded coach on any weekday

## What changed

- The real-backend journey fixture looked up the seeded coach through `GET /admin/sessions` with no date. That route lists only today's classes, and the seeded coach's classes meet on Thursdays, so every journey failed its setup on the other six days. The lookup now asks for `window=upcoming`, the 30-day window that always contains a Thursday. Test-only change.
- The attendance journey opened the coach session page without `?date=`, so the page fell back to the browser's UTC date. After 6 pm in Chicago that date is already tomorrow, so the page said "Session not found." The journey now passes the academy date, as the app's own links do.

## Deploy notes

- None.

## Risk / rollback

- Test-only. Rolling back makes the Frontend E2E Real Auth check fail again on every day except Thursday.

PR: #1154
