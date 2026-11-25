# coach-dated-class-attendance-clarity

PR: #TBD

## What changed
The coach class screen now shows the class date with its time and timezone
("Wed, Nov 25 · 5:00 PM – 6:00 PM CST · Court 2"), so two similarly named
classes on the same day are easy to tell apart. Before class, the banner and the
disabled "Mark rest present" button now give the same opening time ("Opens at
4:00 PM CST"), one hour before the start. The button used to say attendance
opened "when class starts". The Skills screen shows the class date and says
that skill changes don't record attendance.

## Deploy notes
None. Frontend copy only. No API, migration or env change. The server's
one-hour marking rule is unchanged.

## Risk / rollback
Display text only. Roll back by reverting the PR.
