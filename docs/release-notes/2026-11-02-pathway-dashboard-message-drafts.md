# pathway-dashboard-message-drafts

PR: #1106

## What changed
On the owner skill-pathway dashboard, "Message parent" (Almost there) and "Offer a 1-on-1" (Stuck) now open the existing admin direct-message composer addressed to that child's parent, with an editable draft already in the box (the child's first name, the level, the one skill left and the next level, or skills passed and how long since the last win). Nothing is sent until the owner presses Send. `/admin/messages?dm=<parent_id>` now also accepts `&draft=<text>` to prefill the composer, and the dashboard API rows carry `parent_id`.

## Deploy notes
No migration, no env vars. The backend adds an optional `parent_id` field to the `almost_there` and `stuck` rows of `GET /api/v2/admin/pathway/dashboard`; deploy backend and frontend together. If the frontend ships first, the buttons fall back to the student page as before.

## Risk / rollback
Low: read-only API field plus a prefilled text box; sending still goes through the existing DM endpoint on an explicit click. The academy has no private-lesson booking, so the 1-on-1 draft asks the parent to reply rather than linking a booking page. Revert this PR to roll back.
