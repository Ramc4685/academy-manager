# coach-local-day-bounds

PR: #565

## What changed
Coach date queries bucketed occurrences by UTC day bounds even though
occurrences are stored as UTC instants for academy-local class times, so
a 7:00pm CDT class (00:00 UTC the next day) never showed in the coach
Today view on its real local date — attendance marking, the daily
teaching plan, and coach digests were off by a day for every evening
session — and month-end evening classes rolled into the next month's
payroll (`#510`). `list_for_coach_on_date` now fetches a widened (±1
day) UTC candidate window and `ListCoachOccurrencesForDate` narrows to
the requested date in each session's own timezone (UTC fallback for
sessions without one). `GET /coach/today` defaults "today" to the
academy-local calendar date via a new `get_academy_timezone` lookup, and
the admin payroll routes compute the month window in the academy
timezone before converting to UTC.

## Deploy notes
No migration and no data changes — occurrence storage is untouched; only
query windows moved. Academies whose `academies.timezone` is still the
bootstrap default `"UTC"` keep today's payroll-window behavior until an
admin sets their real timezone; the per-session day bucketing fix applies
everywhere immediately because it reads each session's own timezone.

## Risk / rollback
Payroll month boundaries shift by the academy's UTC offset once a
timezone is set, so a month-end evening class moves from one month's
payroll to the adjacent one — recompute affected months rather than
comparing against pre-fix exports. Revert the merge to restore UTC
bucketing; nothing persisted needs cleanup.
