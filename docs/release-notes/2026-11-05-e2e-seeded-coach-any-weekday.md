# Real-backend journeys find the seeded coach on any weekday

## What changed

- The real-backend journey fixture looked up the seeded coach through `GET /admin/sessions` with no date. That route lists only today's classes, and the seeded coach's classes meet on Thursdays, so every journey failed its setup on the other six days. The lookup now asks for `window=upcoming`, the 30-day window that always contains a Thursday. Test-only change.

## Deploy notes

- None.

## Risk / rollback

- Test-only. Rolling back makes the Frontend E2E Real Auth check fail again on every day except Thursday.

PR: TBD
