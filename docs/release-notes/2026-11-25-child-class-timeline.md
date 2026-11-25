# child-class-timeline

PR: #1242

## What changed
A child's progress page now opens with their class timeline, newest first, ahead of current level progress. Each class shows its date (with the year), the class lesson, what this child practised, and "Passed at this class" only on the class whose demonstration earned the pass, and only while the pass still stands; a pass taken back and re-earned later shows only on the later class. A practice repeated across classes shows on every date it happened. A group lesson the coach did not credit to the child never claims they practised. Older classes load a page at a time with "Show older classes", ordered by class start with a stable tie-break across batches. The old "✓ passed as of today" mark is gone from the timeline; current mastery stays in the level section. Coach report text and other children never appear.

## Deploy notes
None. No migration: `earned_pass` is a new optional field on class-observation `test_attempts`, set when a class pass finishes. The parent timeline query adds an optional `cursor` and returns `next_cursor` and `earned_skills`; it drops the per-skill `passed` flag. Deploy backend and frontend together as usual.

## Risk / rollback
Passes recorded before this release have no `earned_pass` flag, so they don't show as "Passed at this class" on older dates. Their current mastery still shows in the level section. Parent-visible coach cues are not part of this step (they arrive with the verbal report, step 6). Roll back by reverting this PR: the field is ignored by older code.
