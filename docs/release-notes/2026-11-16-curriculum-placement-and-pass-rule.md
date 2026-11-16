# curriculum-placement-and-pass-rule

PR: TBD

## What changed
Placing a student on a level now keeps every skill they already earned, and withdraws a level-up that was waiting for approval. The old level is marked completed only when every required skill was passed. Progress taps and tests always land on the student's current level, and the next level skips retired ones.

Each skill now has a pass rule: one tap (the default), N taps in total on any days (2 to 10, default 3), or lead coach only. Lead coach means a coach who is not assistant-only, or an admin or owner. The rule applies to every route that can pass a skill: the tap, the coach test and the admin test. A skill already passed stays passed when its rule changes later. Undoing a lead-coach pass, or failing it with a test, also needs a lead coach. A coach can undo a mistaken try on a skill that is not passed yet.

Admins can select up to 50 students on the pathway progress page, place them on a level, and credit skills they already have. Credits never queue a level-up, even when they cover every required skill (a coach uses the level-up action), and they stay out of the parent email and the monthly report card unless the admin turns it on.

The admin API can now retire and reorder levels and skills; there is no screen for it yet. A level with students on it, or one a waiting level-up points to, cannot be retired (409), and levels cannot be reordered while level-ups are waiting. Approving a level-up into a retired level is refused and the recommendation stays pending. New levels and skills are numbered by the server after every existing row, retired ones included, so adding one after a retire no longer fails; a client-sent `sequence` is ignored. Retiring a skill re-checks that level's students for a level-up.

The parent evening email now covers 19:00 yesterday to 19:00 today in the academy's time, so a class that runs past 19:00 shows up the next evening instead of never. The coach's AI note for today's session drafts against that same window, so a tap after 19:00 goes into tomorrow's email. An approved AI note now also prints on a day the child finished a level. The passport loads all test attempts in one query.

## Deploy notes
None. No migration, env var or index change. Skills stored without a pass rule read as one tap.

`backend/scripts/skill_wipe_audit.py` is a read-only report of students hit by the November placement wipe: skill rows reset to NOT_STARTED despite a passing test, and levels marked completed with required skills missing. Run it with `MONGO_URL` and `DB_NAME` before deciding on a repair. It writes nothing. Its rows can be false positives (coach-approval-only or points-based levels, and skills added after a student finished a level), so check each before a repair.

## Risk / rollback
An assistant-only coach now gets "needs a lead coach" on lead-only skills, and the test routes return `403 StudentProgress.PassNeedsLeadCoach` for them. On an N-taps skill, a passing test counts one tap toward N instead of passing outright. Reordering is two passes of writes and is not atomic: a crash between them leaves sequences above the old maximum, still in order, and the next reorder lifts past them instead of colliding. Roll back by reverting the merge commit; pass rules saved on skills are ignored by the old code.
