# One class form with a pricing plan picker

PR: #TBD

## What changed

- Create session, Edit from the Sessions list and Edit session on the class page now use one shared class form (`frontend/components/admin/sessions/class-form.tsx`): Coach, Name, Location, Day of week (or the read-only date of a one-off class), Start, End, Capacity, Timezone (Create only, as before) and Price. Create still fills the end time from the academy's default class length and the capacity from its default class size.
- Price is a plan picker for the owner: every active Pricing plan ("Group class · $60 / month") plus "Custom price", which shows the monthly fee box. Picking a plan sets the class fee to the plan's current price, saves the class, then links it through the Pricing page's existing `PUT /admin/pricing/classes/{id}/plan`. Picking "Custom price" unlinks. The picker starts at the class's current link, or Custom when it has none or the link is stale. Billing still reads the class fee (`amount_cents`) exactly as before; no billing code changed.
- A non-owner never loads the plan list (it is owner-only) and sees the price read-only ("$60/month" or "Not set") with the owner-only note. The "Scheduled: $X from <Month>" note stays, now also in the list's Edit dialog.
- The "Reason" box is now "Why is the price changing?" and appears only when the price actually changes. An edit that does not change the price sends no `amount_cents` and no `reason`, so it cannot write a fee or a `session_fee_changed` audit row.
- The Communication pack section left the Edit dialog (the class page's Welcome email tab takes it over). The edit PATCH no longer sends any pack field; the backend PATCH is `exclude_unset`, so stored pack values stay as they are. A new backend test pins this.
- Create has an optional, collapsed "Welcome email (optional)" step: WhatsApp group link, venue address, parking notes, what to bring, arrive N minutes before, coach contact and absence & make-up policy. Academy defaults (Class defaults and the Family policies absence text) show as placeholders; only typed fields are sent, so a blank field keeps using the academy default.
- If the class saves but the plan link fails, the dialog says so (Edit keeps the dialog open; Create closes and shows a warning on the Sessions list, since retrying Create would duplicate the class).

## Deploy notes

- Frontend only. No migration, no backend route change (the create route already passed the pack fields through).
- BLNO: classes, fees, invoices and welcome emails are unchanged. The owner sees each class's current plan link in the picker; saving without touching the price writes no fee.

## Risk / rollback

- Medium-low, money-adjacent: the price field changed shape. Guarded by unit tests that a save without a price change sends no fee, that a non-owner never sends one, and that a plan pick sends the plan's price.
- Ship with (or after) the class page Welcome email tab: on its own, this PR leaves no screen that edits an existing class's pack (the class page's "Edit communication pack" button opens the Edit dialog, which no longer shows the pack). Stored values and the welcome email are unaffected.
- Rollback: revert the PR. No data shape changed.
