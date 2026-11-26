# Persona usability study: fixes for owners, front desk, coaches and parents

PR: TBD

## What changed
Six personas (owner, front desk, veteran coach, new coach, busy parent, new family) used a local copy of the demo academy. Their findings became a 71-step plan, built on one branch with a commit per step.
- **Payroll and money.**
  - Generate no longer fails on a coach with an unpaid class, and generate errors now show.
  - Unpriced classes are kept apart from free ones. Parents can't register for them, and the dashboard flags them.
  - The transfer dialog spells out the price change and who is emailed.
  - Late-fee changes ask for a tick before they save.
  - The dashboard warns about students with no invoice for the month and about a starter waiver that was never replaced.
  - Invoices and aging export as CSV.
  - Session economics names each class's coach.
  - Money and setup actions appear in the audit log.
  - Times show in the academy's timezone.
- **Admin Today.**
  - The dashboard opens on today's classes, including on a phone.
  - Each class has a roster sheet. The printed roster shows a health flag, never the note.
  - Quick actions: Absent, Running late, Coach is sick (a three-step cover flow) and New walk-in.
  - People search finds parents by phone.
  - Admins can correct any attendance mark, with a reason.
  - Lists refresh straight after a write.
- **Coaches.**
  - Rosters refresh after a reload, and the service worker serves the network first.
  - Health alerts show on the roster, Today and the plan, read from a separate endpoint that is never cached.
  - Passport links and not-found states are fixed.
  - Children are placed on a level when they enrol, and coaches can place a child who has no level.
  - A coach's "Share with parent" note now reaches the parent.
  - New pages and controls:
    - My week and a first-login welcome.
    - What we teach (`/coach/pathway`).
    - A Pay page showing the coach's own payslips and no per-class amounts.
    - In-app and email notices when a coach is assigned or a class changes.
    - "I can't make it".
- **Parents.**
  - Sign-up wording is fixed, and adding a child starts at the child step.
  - A child can register for a second class.
  - A parent can undo an absence they reported, until class starts.
  - Home shows a "before your first class" card.
  - The Payments page shows one amount, one due date and a line per child, and a paid invoice has a printable receipt.
  - Parents can message the academy. All admins see the family thread, and admins get one email per family per hour that names the family but never includes the message text.
  - The calendar offers an .ics download.
- **Public page.**
  - Each class shows what to bring and its level, and the page links the refund policy.
  - A class can be published from its own page.
- **Shared.**
  - Saves confirm with a toast.
  - One confirm dialog replaces the browser's own confirm.
  - Wording follows the new `GLOSSARY.md` across all three apps.
  - Creating or editing a class refuses a coach or assistant who isn't a member of the academy.

## Deploy notes
One data migration, `0249_registration_lock_per_class`, applied by the release command. It rewrites the registration lock on enrollments made before this change from the child's id to child-and-class, so the existing unique index again stops two near-simultaneous registrations of one child into one class. It cannot collide (the old index allowed one live lock per child) and is safe to re-run. There are no new settings. The parent calendar feed already depended on `UNSUBSCRIBE_TOKEN_SECRET`; this change only adds a plain message when the feed is unavailable. The demo-academy seed is unchanged; the persona test data lives in `scripts/dev/persona_kit/`, which is local only and refuses non-localhost.

## Risk / rollback
The change touches a lot of screens but stores little new data.
- **New collections or fields:**
  - parent message threads and their rate-limit counts
  - coach cover requests
  - a `shared_at` stamp on coach skill notes
  - audit rows
- **Behaviour changes to watch:**
  - Unpriced classes vanish from parent sign-up.
  - Classes whose coach has left the academy can't be copied until a member coach is picked.
  - Withdrawing a reported absence deletes it and writes an audit row.
- **Staff email:** a family's first message in an hour emails every admin and owner (notification category, so the email preference gate applies).

Roll back by reverting the merge commit. None of the new data is read by older code; older code compares locks only for equality, so rewritten locks are harmless to it.
