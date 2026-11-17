# front-desk-tools

PR: TBD

## What changed
Settings > Academy profile has a new Closure dates card: pick the first and last day closed and a reason, preview the class dates, then cancel them all in one step. Each date goes through the same cancel as doing it by hand (the families are credited the date's share, the coach is not paid, make-ups and trials re-open, guests are told), but each family gets one email listing every class it loses, and each coach and admin gets one summary. Closures can be set up to 60 days ahead. Families has a new "New family" form for walk-ins and phone sign-ups: parent, child, optional class and optional login invite, checked against existing families first (a match gets the child added to that family).

## Deploy notes
None. No migration and no new setting. `POST /api/v2/admin/closures` is new; the family import rows now also carry `student_id`.

## Risk / rollback
- Risk: a closure cancels every scheduled class in the range across the academy, with credits and emails. The preview lists the dates first, and re-running the same range cancels nothing new and sends nothing.
- A class time edited after a closure re-materialises the new time slot as scheduled inside the closed range (same as a hand-cancelled date today); cancel it again or re-run the closure.
- Quick add runs import, enrollment and invite as separate calls. If the enrollment or invite fails, the family is still saved and the form says which step to finish from the family page.
- Rollback: revert the PR. Cancelled dates stay cancelled, as with any hand cancel.
