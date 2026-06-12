# prod add BLNO students

## Current State

Status: active

## Problem

Verify additive production Mongo load for five BLNO students, parent users/memberships, roster enrollments, and billing-related rows after explicit data confirmation.

## Changed Files

- None recorded yet.

## Log

- 2026-06-10T16:35:59 main/NA: Task ledger created.
- 2026-06-10T16:36:04 main/blocked: Production student add requested. Reviewed existing BLNO production load history, safe bundle apply helper, session IDs/prices, and admin roster path. No production write attempted; blocked on confirming billing/session/data ambiguities before preparing dry-run bundle.
- 2026-06-10T16:47:55 main/done: Added five BLNO students to production Mongo with parent users/memberships, active enrollments effective 2026-06-01, waiver acceptances, June pending payments, dues snapshots, and corrected reserved_seats on affected Wednesday sessions. No Firebase users were created.
## Verification

- No verification recorded yet.
- 2026-06-10T16:47:43: Pre-write production backup created and downloaded: .local/prod-backups/academy-manager-pre-blno-add-students-2026-06-10-2145.jsonl.gz.
- 2026-06-10T16:47:43: Production dry-run applied no writes and reported expected counts: users=4, academy_memberships=4, students=5, enrollments=5, payments=5, dues_snapshots=5, waiver_acceptances=5, sessions=2.
- 2026-06-10T16:47:55: Production apply succeeded with expected applied counts: users=4, academy_memberships=4, students=5, enrollments=5, payments=5, dues_snapshots=5, waiver_acceptances=5, sessions=2.
- 2026-06-10T16:47:55: Bundle identity verification succeeded: all 4 users, 4 memberships, 5 students, 5 enrollments, 5 payments, 5 dues snapshots, 5 waiver acceptances, and 2 session docs matched; missing={}.
- 2026-06-10T16:47:55: Post-apply functional checks: Wednesday 5:45 session active_count=11 reserved_seats=11 capacity=15; Wednesday 6:15 session active_count=15 reserved_seats=15 capacity=15; five new student rows have skill_level=intermediate and waiver_accepted=true; five June 2026 pending payments at 7000 cents each total 35000 cents due; production healthz returned ok.
## Reusable Lessons

- None recorded yet.
