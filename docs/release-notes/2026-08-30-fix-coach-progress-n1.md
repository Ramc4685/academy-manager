# coach-progress-n1

PR: #586

## What changed
The coach pre-class views were N+1 on Mongo. `GET
/coach/sessions/{id}/students-progress` awaited `GetProgressSummary.execute`
once per roster entry, and each summary issued ~6 sequential queries (active
level, certificates, active recommendation, level metadata, level skills,
per-level skill progress). `GetSkillBoard` — behind both the coach and admin
skill-board endpoints — likewise called `get_active` and
`get_active_for_student` once per student. A 20-student roster meant 120+
sequential round trips, so the views degraded linearly with roster size on
Fly-to-Atlas latency.

The student_progress repos gained batch methods using `$in` on `student_id`
(`list_active_for_students` on level progress and recommendations,
`list_for_students` on certificates), all tenant-scoped through
`TenantScopedRepository` like the per-student queries they replace.
`GetProgressSummary.execute_many` now loads a whole roster with three batch
queries plus three lookups per distinct active level and builds every overview
in memory; the coach students-progress route calls it instead of looping. The
single-student `execute` is behaviorally unchanged and shares the same
overview-building helpers. `GetSkillBoard` batches its active-level and
recommendation lookups the same way.

## Deploy notes
No migration: no new collections or indexes. The batch queries filter on the
same fields as the existing per-student queries, with `$in` on `student_id`.
API responses are byte-identical; only the query pattern changed.

## Risk / rollback
Main risk is a behavior drift between `execute` and `execute_many`; a parity
test asserts both paths produce identical overviews for the same student, and
query-count tests pin the batch shape so a per-student call cannot silently
return. Recommendation lookup keeps last-write-wins semantics if a student
somehow had multiple active recommendations (the old `_find_one` picked one
arbitrarily too). Roll back by reverting the merge commit — no persisted state
changes.
