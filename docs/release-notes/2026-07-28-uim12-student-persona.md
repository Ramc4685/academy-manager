# uim12-student-persona

PR: #371

## What changed
Adds a read-only "student" login persona so older students and adult learners can see their own schedule and progress without going through a parent account. Admins can send a student a set-password invite from the student record (`POST /admin/students/{student_id}/login-invite`), and the student gets three pages: dashboard, schedule, progress. The whole surface — reads and invites — ships dark behind `enable_student_login`, which defaults to false.

## Deploy notes
Migration `0150_student_login_link` adds a unique partial index on `(academy_id, student_user_id)` in the `students` collection. It is additive and safe to run on existing data (it `$unset`s explicit nulls first so the partial filter is not tripped). No env vars. `enable_student_login` stays false until an academy is explicitly opted in; enabling it is a per-academy product decision, not a deploy step.

## Risk / rollback
The identity change touches claims loading for every persona, so a regression would surface as broken login for admin/coach/parent — covered by regression tests, but it is the thing to watch after deploy. The critical control is claims → `student_id` resolution: a mis-resolution would show one student another student's data. That is enforced one-to-one in both directions (unique partial index, application-level pre-check, and a fail-closed lookup that returns nothing rather than an arbitrary match if duplicates ever exist).

Rollback: set `enable_student_login=false` — instant kill switch for both the read routes and the invite route. Reverting the PR is safe; any `student_user_id` values left behind are inert. Note there is no unlink/re-invite path yet, so a typo'd invite email permanently burns that student's login until a DB edit — worth fixing before enabling the flag for a real academy.
