# batch-11: family invoice actions

PR: #901

## What changed
- Fixes #890 — the family page now gives each money action exactly one home: invoice rows keep only the two row-specific actions (Record payment, Send) as direct buttons, with a new More menu holding the draft-only Add charge; void, refund, one-time discount and charge-card-now no longer render on the row, so the Fix panel is their single home.
- Fixes #890 — the autopay-failure card's duplicate "Record payment" button (same handler as the header's primary button) is removed, leaving the header as the one general entry point.
- Fixes #890 — the Fix panel's two disabled "coming later" placeholders (Account credit, Undo manual payment) are removed, along with the now-dead `DisabledFixItem` component.

No eligibility, API call, idempotency key, or dialog wiring changed — only which component renders which trigger.

## Deploy notes
No migrations. Frontend-only change; no manual steps required before or after deploy.

## Risk / rollback
Low risk: purely a UI reorganization of existing, already-wired actions (no new API calls or eligibility logic). If a money action turns out to be harder to find than before, revert this PR's merge commit.
