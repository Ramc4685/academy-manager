# batch-10c: four verified UI quick wins from the design critique

PR: #889

## What changed
- Fixes #888 — `rally-cobalt` now has a default shade, so the ~23 places that used it without a number finally render: the Waitlist "Manage session" link is visible, and cobalt hover and focus borders appear (keyboard focus was invisible there).
- Fixes #888 — Parent bottom-menu labels for inactive tabs are readable (contrast about 2.5:1 before, 7.5:1 now).
- Fixes #888 — When an admin direct message fails to send, the error is shown on screen instead of only to screen readers.
- Fixes #888 — "Disconnect Stripe" in Settings now asks for confirmation and states that card payments and autopay stop until an account is reconnected.

## Deploy notes
No migrations. Frontend only. No environment changes or manual steps.

## Risk / rollback
Low. Visual: elements that were meant to be cobalt now are. Behaviour: one extra confirmation before disconnecting Stripe; the API call is unchanged. Roll back by reverting this PR.
