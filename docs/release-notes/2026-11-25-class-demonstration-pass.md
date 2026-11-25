# class-demonstration-pass

PR: TBD

## What changed
A class's lead coach, substitute or the owner can now record that a child met a skill's criterion in a specific dated class, through `POST /api/v2/coach/occurrences/{occurrence_id}/class-demonstrations`. Only children marked present or late for that class can be credited. A skill from another level of the child's program counts toward that skill's own level, and it never completes the child's active level, queues a level-up or issues a certificate. Each test attempt now records when the skill was observed (the class date) apart from when it was entered, and who signed a pass off.

## Deploy notes
None. No migration: `observed_at` and `signed_off_by` are new optional fields on `test_attempts`, which the existing validator allows. The route has no frontend caller yet; the recap save in the next step uses it.

## Risk / rollback
If off-level passes were wrong they would show on the parent's all-level view as earned skills on a higher level, never as a level change. Roll back by reverting this PR; recorded attempts stay valid history and the existing tap-to-master and test routes are unchanged (they still refuse off-level skills).
