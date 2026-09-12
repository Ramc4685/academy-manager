# Coach Today no longer 500s on held students

PR: #756

## What changed

- Fixes #732 — `GET /api/v2/coach/today` returned a 500 for a coach's entire day as soon as any student on any of that day's classes was on hold. The roster deliberately keeps held rows visible (#697), but the coach BFF response DTO (`CoachRosterEntry.enrollment_status`) only accepted `active`/`paused`/`cancelled`, so pydantic rejected the row and the whole day's payload failed to serialize.
- Widened `CoachRosterEntry.enrollment_status` to also accept `held`. This is a DTO-only, additive change with no route, use-case, or migration impact, and no frontend code reads this field.
- Added an interface test that seeds a held enrollment on one of the coach's sessions and asserts the endpoint returns 200, both sessions still render, and the held student appears with `enrollment_status: "held"`.

## Deploy notes

- No migration. No new environment variables. Backend-only change; frontend is untouched because no frontend code reads `enrollment_status`.

## Risk / rollback

- Low risk: strictly widens an accepted enum value on a response DTO; no behavior changes for non-held enrollments.
- Rollback: revert this PR. The prior 500 behavior for held-student days would return, but no other regression risk.
