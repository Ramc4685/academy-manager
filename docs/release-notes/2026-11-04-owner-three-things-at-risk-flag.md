# owner-three-things-at-risk-flag

PR: #1132

## What changed
The 07:30 owner brief now opens with "Three things today": failed cards in the window, open "trial passed, no registration" follow-ups, and families with a child whose attendance has stopped, each with a count and up to five family names linked to the family record. The Families list and the family record header show an "At risk" chip whose tooltip names the reason (attendance, payment), computed by the server from the signals the family card already carries; the 30/60/90 win-back wording is unchanged.

## Deploy notes
none (no migration, no new env var; the brief reads the existing People CRM family index and `FRONTEND_URL` for links)

## Risk / rollback
If the family index cannot be read, the at-risk line says "could not be read" and the other two lines fall back to raw parent ids; the rest of the brief is unaffected. A wrong rule only mislabels a chip or a brief line, no money or data moves. Roll back by reverting the PR; nothing persisted needs cleaning up.
