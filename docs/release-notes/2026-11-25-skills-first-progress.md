# skills-first-progress

PR: #1238

## What changed
The parent progress page now lists every level of the child's pathway with
required and optional skills passed in each, including skills earned ahead of
the current placement. A level shows as done only when its placement was
completed or every configured required skill is passed; a lower level number
alone no longer implies completion. Retired skills drop out of the counts, a
level with no required skills says so, and quiet placement credits count but
do not appear as recent wins. The coach progress summary uses the same
counting. New level-up recommendations and automatic approval now require at
least one configured required skill.

## Deploy notes
No migration or configuration change. The program-wide skill read uses the
existing `(academy_id, student_id, program_id)` index. Academies with
optional-only levels must configure a required skill before a promotion can be
recommended. Owners reviewing an already queued recommendation should check the
current requirements before approving it by hand.

## Risk / rollback
Roll back the progress view and the completion-rule change together if counts
or promotion readiness look wrong. The view only reads existing skill records,
so rollback loses no data.
