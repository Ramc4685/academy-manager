# coach-phone-attendance-notes

PR: #TBD

## What changed
Coach app on phones (role-model slice 3): attendance is one tap per student
with 44px Present/Absent targets and a "Mark all present" action; taps made
while offline are queued on the phone and sent on reconnect (server-saved
marks still need a connection to change). Skill passport and skill-board
controls meet the 44px target on phones. Coach notes now have an audience:
every progress note and skill note is **private by default**, a coach can
tick "Share with parent" when writing it or flip it later, parents see only
shared notes, and assistant coaches can write notes but never share them
(the API refuses with 403). Owners and admins see every author's notes on a
session.

## Deploy notes
Migration `0167_coach_notes_visibility_private` marks every existing
progress note and skill note as private. It does **not** run on boot in
production (`V2_RUN_MIGRATIONS_ON_BOOT` is off, #629): after Deploy Backend
succeeds run it by hand and report the modified counts for both collections:

```
fly ssh console -a courtmastr-academy-api
python -c "import asyncio; from backend.v2.migrations.runner import run_pending_migrations; asyncio.run(run_pending_migrations())"
```

(Use whatever entry point was used for 0165 if the module path differs.)
Until it runs, notes without the field already read as private, so parents
see no coach notes either way. Expect parents to lose every previously
visible coach note until a coach re-shares it — tell coaches. No env vars.

## Risk / rollback
Medium for parents (notes disappear from the parent feed until re-shared);
low elsewhere. Revert the PR to restore the old coach screens; the old code
ignores the `visibility` field, so parents would see every note again
(including ones coaches meant to keep private) — re-run nothing, the field
is harmless. Offline queueing only replays first marks through the existing
idempotent `/coach/attendance` endpoint; a rejected replay lands in the
coach's Needs-review tray instead of being lost.
