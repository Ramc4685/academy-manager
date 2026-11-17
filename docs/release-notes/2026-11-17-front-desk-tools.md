# front-desk-tools

PR: TBD

## What changed
Settings > Academy profile has a new Closure dates card: pick the first and last day closed and a reason, preview the weekly class dates (dates the cancel rules refuse, such as a frozen payout period, show as not cancelled), then cancel them all in one step. Each date goes through the same cancel as doing it by hand (the families are credited the date's share, the coach is not paid, make-ups and trials re-open, guests are told), but each family gets one email listing every class it loses, and each coach and admin gets one summary. The result shows billing warnings, families with no email on file, and whether the emails failed. Closures can be set up to 60 days ahead and cover weekly classes only; one-off classes are cancelled from their class page. Families has a new "New family" form for walk-ins and phone sign-ups: parent, child, optional class and optional login invite, checked against existing families first (a match gets the child added to that family).

## Deploy notes
None. No migration and no new setting. Fixes a latent bug on main: saving a weekly class (and now previewing a closure) re-materialised today's class dates that had already started, so a class cancelled this morning came back as scheduled and a substitute coach recorded this morning was wiped. Started dates are now left alone. `POST /api/v2/admin/closures` is new; the family import rows now also carry `student_id`.

## Risk / rollback
- Risk: a closure cancels every scheduled weekly class in the range across the academy, with credits and emails. The preview lists the dates first. Re-running the same range cancels nothing twice. A date that fails for an unexpected reason is shown as "failed, retry" and the rest go ahead; re-running retries it. If the server dies or is redeployed mid-run, the dates it had already cancelled are never in a family email (a re-run skips them), so tell those families by hand; resuming that summary is a follow-up.
- A class time edited after a closure re-materialises the new time slot as scheduled inside the closed range (same as a hand-cancelled date today); cancel it again or re-run the closure.
- Quick add runs import, enrollment and invite as separate calls. If the enrollment or invite fails, the family is still saved and the form says which step to finish from the family page.
- Rollback: revert the PR. Cancelled dates stay cancelled, as with any hand cancel.
