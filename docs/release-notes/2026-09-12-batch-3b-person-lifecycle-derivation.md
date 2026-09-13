# Person lifecycle derivation

PR: #0

## What changed

- Fixes #773 — `students.status` was free text whose only writer was the admin edit form: Drop, Stop-all, Pause, Hold and hold-expiry never touched it, so every child ever registered read ACTIVE, the Paused tile counted only the 25 loaded rows, and paused children vanished from `/parent/children` entirely. The person lifecycle (8 states, precedence R1-R6 from the issue's derivation spec) is now derived once in `backend/v2/contexts/enrollment/domain/lifecycle.py` — reusing the enrollment-status predicates from PR #766 — from enrollments, holds, pending cancels and attendance, computed before the directory's limit+1 slice so `lifecycle=` filters and summary counts describe the whole academy rather than just the loaded page. The derivation is threaded through admin (`directory_routes.py`, `admin_directory.py`), parent (`parent.py` composition, `parent/views.py`) and coach (`today_routes.py`, `coach/views.py`) reads. The Status select and `UpdateAdminStudentCommand.status` are gone; `partitionByHold` no longer drops live rows; and the coach roster's response-validation `Literal` now admits `reclaim_pending` (a #732-class crash) and renders the hold return date.
- Follow-up fix (review on #773) — the pathway-progress student listing was still calling `ListAdminStudents.execute()` with the retired `status="active"` parameter; updated it to the renamed `lifecycle=("active",)` parameter and aligned the route's test fake with the real use case's signature so this class of regression (a route silently drifting from a renamed use-case parameter) is caught going forward.
- Fixed during this gate — `mongo_student_repo.py`'s lifecycle-filter list comprehension read `row["lifecycle"].state` off a `dict[str, object]`-typed row under a blanket `type: ignore`; replaced with an explicit `cast(PersonLifecycleState, ...)` to satisfy mypy without suppressing real type errors on that line.

## Deploy notes

No migrations. No new environment variables or feature flags. `students.status` is no longer read for lifecycle purposes on any of the three persona surfaces (admin, parent, coach); the field itself is left in place and unused, not dropped, so no backfill is required. Frontend and backend ship together (the admin Status select removal and the shared derivation are both in this PR); no manual steps before or after deploy.

## Risk / rollback

- The derivation replaces a single free-text field read across three persona surfaces with one shared domain function, so a bug in `domain/lifecycle.py` affects admin, parent and coach reads simultaneously rather than independently — mitigated by the full v2 test suite (4836 tests) passing, including lifecycle-state coverage for all 8 states and the R1-R6 precedence rules.
- Widening the lifecycle/attendance queries from "the page" to "everyone who matched the search" (to compute correct summary counts and filters before pagination) is a constant number of extra round trips per directory request, not one per student, but it is still additional Mongo load on large academies — worth watching after deploy.
- Rollback: revert this PR. No data migration to reverse; `students.status` was never removed from the schema, so no reconciliation is needed if the old code path is restored.
