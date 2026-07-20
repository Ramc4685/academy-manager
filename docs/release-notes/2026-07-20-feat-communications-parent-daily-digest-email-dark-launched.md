# feat-communications-parent-daily-digest-email-dark-launched

PR: #308

## What changed
A per-family **parent daily digest** emailed on session mornings, plus wiring the previously-inert admin CC on the coach digest to its existing settings toggle.

Two rendered variants, chosen per family by portal status:

- **Variant A** (parent has activated the portal): per-child card with today's focus + status chip, level progress (skills left, levels to go), a can't-make-it deep link into the parent requests (absence) flow, and conditional dues / autopay rows.
- **Variant B** (never activated — the defaulter population): dues-forward "set up account & pay" CTA, progress teaser, and a reply-to fallback for absences.

## Deploy notes
Includes migration(s): backend/v2/migrations/0148_parent_digest_send_indexes.py. Confirm `V2_RUN_MIGRATIONS_ON_BOOT` covers it or run manually — see AGENTS.md.

## Risk / rollback

**Blast radius is bounded by the dark launch.** Both `notifications.parent_digest_enabled`
and the admin-CC toggle (`notifications.daily_digest_to_admin`) default off, and the
real Resend sender is only wired when `email_delivery_enabled` + `resend_api_key` are set
**and** `env` is `staging`/`prod` (otherwise the stub is used). Merging sends no email in
production until an admin flips the per-academy toggle.

**What could break if this is wrong:**
- A wrong local-day window could email a family with no session today, or skip a family
  whose evening session crosses the UTC date boundary (day bounds are computed in the
  scheduler timezone before querying UTC-stored occurrences).
- A misconfigured non-prod deployment with delivery flags + Resend creds could email real
  parents — guarded by the `env in {staging, prod}` gate.
- The dues block surfaces a pay link only for `open`/`partially_paid` invoices (matches the
  parent checkout path); a `draft` invoice will not produce a link.

**Rollback:**
1. Fastest kill switch: set each academy's `notifications.parent_digest_enabled` back to
   off (no deploy needed) — the hourly job then sends nothing.
2. Full revert: revert the merge commit. The feature is additive (new use case, provider,
   `parent_digest_sends` collection via migration 0148); reverting stops all sends. The new
   collection and its indexes are inert once the job no longer runs and can be left in place.
