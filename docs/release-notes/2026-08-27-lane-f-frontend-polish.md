# lane-f-frontend-polish

PR: #462

## What changed
Admin invoice dates no longer display a day early: values stored at UTC midnight now
render on the day they encode, while invoices with a real time-of-day still show the
admin's local day. Placing an unplaced student from the skill board now keeps the
program the admin was working in, so the student resolves on the board they came from.
The Create session dialog no longer wipes typed-in fields when the academy timezone
query resolves late. Also restores ruff formatting on `backend/v2/interfaces/parent/views.py`,
which was left unformatted by #375 and was failing `ruff format --check` on main.

## Deploy notes
None. Frontend-only behaviour plus one backend whitespace fix; no migrations, no env vars.

## Risk / rollback
Low. The date changes are display-only and cover three call sites on the admin student
detail screen; if a date renders unexpectedly, the wrong formatter variant was chosen for
that field. The skill-board link now carries `program_id` and a `return_label`, changing
the back-link text on the student progress screen. Roll back by reverting the PR — each
issue is a separate commit and can be reverted independently.
