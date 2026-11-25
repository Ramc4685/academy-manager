# coach-dated-class-attendance-clarity

PR: #1241

## What changed
Fixes from the Nov 25 academy usability study, so a coach picks the right dated
class, saves one mark, and an admin finds that same mark.

- Coach class screen shows the occurrence's own weekday and date with its
  academy-time range and timezone ("Wed, Nov 18 · 4:00 PM – 5:00 PM CST"), even
  for a one-off class under a different regular day, and after reload.
- Before class, the banner and the disabled "Mark rest present" button give the
  same opening time, one hour before start. The gate and label share one parser.
- Skills screen shows the class date and says skill changes don't record
  attendance. The class recap says whether it is saved; Needs review explains it
  only holds marks that didn't sync on this phone.
- Admin Sessions list labels days as the regular schedule, explains that one-off
  or moved classes need Class dates, and adds a Class dates action per class
  (desktop button, phone menu). Class date rows show weekday and year.
- Admin Inbox tabs read "Makeup requests", "Absence notices", "Pause requests".
  Settings points to Staff for giving a coach or admin access.
- Invoice detail links to the family's Billing tab for each payment's method, date
  and Stripe reference; the deposit slip links to all invoices.
- Admin student progress shows the date each skill was passed, in the
  academy's timezone (test dates too).
- Parent Profile and Children show each child's waiver state with a sign or
  view link. Payments links to the children's next class date and time.
- Sign-up shows the email path as a distinct secondary choice next to Google
  and Apple.

## Deploy notes
Backend adds an optional `passed_at` field to the skill passport and student
progress responses: a PASSED skill's last update, the same date milestones and
the parent journey already use.
Additive only: no migration, index or env change. The one-hour marking rule,
permissions, tenancy and billing behaviour are unchanged.

## Risk / rollback
Mostly copy, links and display. The only server change is a read-only derived
field. Roll back by reverting the PR.
