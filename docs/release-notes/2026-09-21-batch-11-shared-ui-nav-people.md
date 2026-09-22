# Batch 11: shared UI nav/people fixes

PR: #0

## What changed

- Fixes #896 — Moved the Progress page, skill board, and phone calendar onto the Rally design system, matching the rest of the admin UI.
- Fixes #897 — People contact links were muted, hover-underlined, and about 20px tall; they're now cobalt, always underlined, and a 44px tap target on phones (collapsing at the `md:` breakpoint), fixed from one shared component so it applies across every People surface.
- Fixes #893 — Settings no longer silently loses unsaved edits on any in-app exit. The dirty-state guard moved from the settings tab strip up into the admin shell, so a sidebar link, a phone-drawer link, any other in-app link, and a reload/tab-close all warn first. `window.confirm` is replaced by the Rally `ConfirmActionDialog` ("Stay on this page" / "Leave without saving", with a new optional `cancelLabel`); reloads still use the native `beforeunload` prompt since that's the only option available during an unload. Same-document Back/Forward is deliberately left un-intercepted (would require pushing sentinel history entries on every dirty flip, silently rewriting the reader's history); `beforeunload` still covers a Back that leaves the app.
- Fixes #892 — The refund dialog now states the consequence before confirming: money returns to the original payment method, Stripe refunds take 5-10 business days (manual refunds are recorded by the academy), and a refund cannot be undone — behind a danger-outline confirm instead of the cobalt primary action. Billing periods now read as "September 2026" instead of "2026-09" across the invoices list, the refund subject, the invoice label, and the skipped-deferral list. Skip reasons read as full sentences ("Skipped this month"), with a sentence-cased fallback for codes the backend adds later. Raw Stripe ids moved behind a per-row "Stripe details" disclosure on both the phone list and the desktop table, keeping the reconciliation trail available without cluttering the row. Coach utilization now says "No data" instead of "NaN%" on both percent columns. DM threads whose contact is outside the parent-role roster now show the family's real name from the admin directory instead of the literal word "Parent". No refund/void/charge call, idempotency key, or eligibility predicate changed.

## Deploy notes

No migrations. Frontend-only changes (admin UI components, dialogs, and copy); no backend contract or database schema changes. Safe to deploy without any special sequencing.

## Risk / rollback

Low risk — UI/copy/interaction changes only, no money-movement logic touched (refund/void/charge calls, idempotency keys, and eligibility predicates are unchanged). If an issue surfaces, revert this PR.
