# coach-next-class-sync-status

PR: TBD

## What changed
Coach Today, when there are no classes today, now shows the coach's next assigned class (date, time, name, location, with a link to it) and a "Finish your class recap" shortcut to the most recent class from the last two days whose recap is not saved yet. Assistants don't see the recap shortcut. Inside a class, attendance links to "Next: update skills" and the skills page links to "Next: class recap", which opens the class with the recap panel expanded. The class screen shows whether its marks are Saved, Waiting to sync or Need attention. The status comes from the existing offline queue, and Needs attention links to the Needs review tray. Queued marks already persist in IndexedDB and replay with their `mutation_id` as the idempotency key. New tests prove a queued mark survives a restart and is stored exactly once on replay. Coach Profile no longer shows the empty Pay & statements card. The recap's optional AI reading control now sits behind a "More options" disclosure, and the standard recap stays visible.

## Deploy notes
None. No migration, env var or manual step. `GET /coach/today` gains an additive `recap_saved` flag per session (true when that class has a recap with at least one taught skill). Older cached PWA clients ignore it. Push routing is unchanged.

## Risk / rollback
Read-only additions. If the recap lookup fails, the Today response still returns and treats recaps as unsaved, so the worst case is an extra shortcut. Attendance writes, permissions, practice credit and promotion are unchanged. Roll back by reverting the PR.
