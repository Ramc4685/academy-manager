# feat-communications-parent-daily-digest-email-dark-launched

PR: #308

## What changed
A per-family **parent daily digest** emailed on session mornings, plus wiring the previously-inert admin CC on the coach digest to its existing settings toggle.

Two rendered variants, chosen per family by portal status:

- **Variant A** (parent has activated the portal): per-child card with today's focus + status chip, level progress (skills left, levels to go), a can't-make-it deep link into the attendance page, and conditional dues / autopay rows.
- **Variant B** (never activated — the defaulter population): dues-forward "set up account & pay" CTA, progress teaser, and a reply-to fallback for absences.

## Deploy notes
Includes migration(s): backend/v2/migrations/0148_parent_digest_send_indexes.py. Confirm `V2_RUN_MIGRATIONS_ON_BOOT` covers it or run manually — see AGENTS.md.

## Risk / rollback
_Auto-generated stub — author: fill in what breaks if this is wrong and how
to roll back before merge._ Revert the merge commit if this regresses.
