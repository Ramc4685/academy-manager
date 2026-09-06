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
**Run migration `0167_coach_notes_visibility_private` by hand after the
deploy.** Boot migrations are off in prod (`V2_RUN_MIGRATIONS_ON_BOOT=false`,
#629). It stamps `visibility: "private"` on every `progress_notes` and
`coach_skill_notes` document that predates the flag, and is idempotent. The
app already treats a missing field as private, so parents see the same thing
before and after; the backfill makes the parent feed's equality match exact.
No env vars.

**Behaviour change to announce:** every coach note written before this deploy
disappears from the parent progress feed until its coach (or an owner/admin)
shares it again from the session's note box. Tell coaches before the deploy.

## Risk / rollback
Medium for parents (notes disappear from the parent feed until re-shared);
low elsewhere. Revert the PR to restore the old coach screens; the old code
ignores the `visibility` field, so parents would see every note again
(including ones coaches meant to keep private) — re-run nothing, the field
is harmless. Offline queueing only replays first marks through the existing
idempotent `/coach/attendance` endpoint; a rejected replay lands in the
coach's Needs-review tray instead of being lost.
