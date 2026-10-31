# parent-progress-journey

PR: TBD

## What changed
The parent Progress page (where the evening win email lands) now leads with the child's journey: a "Level N of M" strip, a ring showing skills done in the current level with how many are left to the next level, an "At this pace: about N weeks" line when recent passes support one, the level's skills as Got it / Working on it / Coming up, recent wins (skill passes and level certificates), and the practice drill video for the skill the coach is working on. Coach notes move below. Backed by one new parent route, `GET /api/v2/parent/students/{id}/progress-journey`.

## Deploy notes
No migration, no new job, no config. The pace line is omitted unless the child passed at least 3 skills on 2 or more days in the last 8 weeks, and when the estimate is over 26 weeks.

## Risk / rollback
Read-only. If the page misbehaves, revert this PR; the old passport, skill-updates and practice-resources routes are unchanged on the backend.
