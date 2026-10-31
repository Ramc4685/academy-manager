# Attendance summary windows on the class date and stops counting absences as attendance

PR: #911

## What changed

The attendance figures behind the admin students list and student detail (`attendance_rate`, `last_seen_at`, and the `at_risk` lifecycle state derived from them) now:

- window on the date the class actually ran (`session_occurrences.start_at`, joined by `occurrence_id`) instead of on when the coach tapped the mark (`marked_at`);
- look back 30 days, matching the admin UI label "Last 30 days", instead of 90;
- compute "last attended" from present/late marks only, so a student who was marked absent is no longer reported as seen, and an absent-only student has no last-attended date;
- ignore voided marks (#554) in the summary and in the student detail's recent-attendance list.

Attendance rows whose occurrence no longer exists have no class date to window on and are left out of the summary rather than windowed on `marked_at`.

## Deploy notes

No migration, no new index, no config change; the aggregation uses the existing `session_occurrences.occurrence_id` lookup. Frontend unchanged.

Expect a visible change on the first load after deploy: **the at-risk count on admin lists will rise.** Absences no longer count as attendance for `last_seen_at`, and the window shrank from 90 days on `marked_at` to 30 days on the class date, so more students cross the at-risk cutoff. This is the corrected read, not a regression. Individual `attendance_rate` values may also drop for students whose only recent marks belong to occurrences that were later deleted.

## Risk / rollback

Read-model only; no writes, no billing or lifecycle transition code touched. Rollback is reverting the PR, which restores the previous (incorrect) 90-day `marked_at` window and absence-counts-as-seen behaviour. The extra `$lookup` runs once per list request over the matched students' attendance rows; it re-asserts `academy_id` on the joined side so a cross-tenant occurrence id can never leak into a rate.
