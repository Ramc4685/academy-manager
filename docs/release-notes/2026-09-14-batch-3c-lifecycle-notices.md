# Parent notification preferences and undeliverable-email visibility

PR: #825

## What changed
- Fixes #778 (parent-facing) — The GET/PUT `/parent/email-preferences` endpoints have existed since #555 with no portal surface, so the only way a family could change what we email them was the unsubscribe link at the foot of an email they may have deleted. The parent Profile page now has a Notifications card wired to those endpoints; the opt-out/opt-in inversion and channel copy live in a pure, unit-tested module (`frontend/lib/parent/notification-preferences.ts`), and the card sends exactly the three allowed flags since the PUT body forbids unknown keys.
- Fixes #778 (admin-facing) — The suppression list has recorded hard bounces and spam complaints since #556, but nothing admin-facing ever read it: a dead address was invoiced, dunned, and eventually dropped in silence. The family read model now joins the suppression list for the parent's address; the Family page header shows an "Email undeliverable since &lt;date&gt;" chip (with distinct, softer copy for a spam complaint, which only blocks digests, not all mail), and the family timeline gets a muted comms row at the moment delivery stopped. The suppression lookup goes through `_secondary` so a lookup failure degrades to a warning banner instead of a 503 (the #748 pattern).
- Follow-up fix on #778 — froze the family billing warnings tuple after the suppression lookup runs so a failed lookup actually surfaces in the admin warnings banner instead of being silently dropped by keyword-argument evaluation order; added a contract test that fails without the fix.

Not in this PR (tracked separately, see the lane's blocker notes): waitlist offer/confirm/sweep notices, and last-class / pause-ending / first-class / level-up notices. The win-back job (sub-item 1 of the original lane) was already on `main` in `c0c6aeb8c` and needed no porting.

## Deploy notes
- No migrations.
- No new environment variables or manual steps. Both endpoints (`GET`/`PUT /parent/email-preferences`) already exist in production since #555; this PR only adds portal/admin surfaces reading and writing them.
- The suppression-list join reads via the existing `_secondary` Mongo read preference already used elsewhere in the family read model, so no new infra dependency.

## Risk / rollback
- Risk: low. Both changes are additive UI/read-model surfaces over data that already exists (`email_preferences`, the suppression collection); neither introduces a new write path beyond the pre-existing preferences PUT. The suppression lookup is defensive (warns rather than fails the page) so a lookup outage cannot take down the Family page.
- New coverage: `frontend/lib/parent/notification-preferences.test.ts`, `backend/v2/tests/unit/test_family_billing.py`, `frontend/app/(admin)/admin/families/[parentId]/family-view.test.ts`, and `backend/v2/tests/contract/test_family_billing_read_model.py` (pins the warnings-tuple fix).
- Rollback: revert this PR. No data cleanup required — no schema or migration changes.
