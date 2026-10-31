# Calendar: show academy time and fix next-day Sessions links

PR: #1047

## What changed

- Coach Sessions links used the UTC date. Evening classes (and every 6 PM+ Chicago class after DST ends) opened "Session not found". Sessions, Today and Calendar now share one helper that uses the academy-local date (#1045).
- Coach and parent calendars rendered in the browser's timezone, so a travelling parent or coach saw 4 PM for a 6 PM class. They now render in the academy's timezone via `@fullcalendar/luxon3` and show a "Times in …" label (#1043).
- Missing/invalid academy timezone shows a "Calendar times unavailable" card instead of a guessed clock. A failed `/parent/academy` load shows an error with Retry.
- A coach with no upcoming sessions sees "No upcoming sessions." instead of an empty grid.

## Deploy notes

- Frontend only. New devDependencies `@fullcalendar/core`, `@fullcalendar/luxon3`, `@types/luxon` (luxon via peer). Normal build installs them. No env vars or manual steps.

## Risk / rollback

- Low. Academies with no valid timezone now see the "unavailable" card instead of a grid. Rollback: revert the PR.
