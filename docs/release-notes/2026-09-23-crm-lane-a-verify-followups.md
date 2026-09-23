# People CRM follow-ups: family record by any parent id, one invite per family, old parent links

PR: #936

## What changed

- A family record opened by a parent alias now shows the family. Student pages link to `/admin/families/{parent id}` using whatever id the child's row stores (the parent's user id, Firebase uid, older auth uid or account id). `GET /api/v2/admin/families/{id}/record` used to find the family only by its canonical id, so an alias link returned 404 and the Overview and Details tabs showed no stage or balance with no warning. The record now resolves the id through the same alias map the Families list is built from (this academy's rows only; another academy's parent is still a 404), and the response carries the canonical `family_id`. The page then swaps the URL for the canonical one, keeping `?tab=`. If the record cannot be loaded, Overview and Details show a visible error with Try again instead of empty cards.
- "Invite all not invited (N)" on the Families page counts and invites each family once. The Billing Setup list (`GET /api/v2/admin/billing/setup`) built one row per stored parent id, so a family whose children store different ids for the same parent was counted twice and sent two invites. Rows are now grouped by parent, with ids resolved in one batched lookup per id field (no `$or`, no per-row queries). A grouped row keeps an id a child actually stores, so the invite and detail endpoints still find it, and it reads cards, balances and autopay filed under any of the parent's ids. The roster adapter moved from `composition/admin.py` to `composition/billing_setup_roster.py`.
- Old `/admin/parents/{id}` bookmarks now redirect (307) to `/admin/families/{id}` instead of returning 404. This is a config redirect only; no new app route.
- The Families page heading reads "1 family matches this search" and "3 families match this search". The Overdue and No card filter chips show their counts. `GET /api/v2/admin/families/summary` adds `preset_counts` (`no_card` always; `overdue` only for staff who may see money, the same check as every other amount).
- Docs: the People CRM engineering spec now says billing staff record payments (Record payment, mark paid), matching the owner decision of 2026-09-22. Charge, refund, void, add charge, discounts and the autopay toggle stay owner-only.

## Deploy notes

- Backend and frontend ship together. With an older backend the page still works: the record response lacks the top-level `family_id` (the page falls back to `family.family_id`) and the chips show no count for Overdue and No card.
- No migration, no index, no feature flag, no environment variable.

## Risk / rollback

- Low. The record, summary and Billing Setup changes are reads. The one behaviour change with a side effect is that bulk invite sends one email per family instead of one per stored parent id.
- A Billing Setup row for a family with children under two ids now shows one balance: the two ids' outstanding amounts added together, with the invoice offered for charging taken from the row's own id first. Tests cover this, one row per parent, and that another academy's child of the same parent never reaches the list.
- Rollback: revert the PR. Nothing is stored differently.
