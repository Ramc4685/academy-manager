# family-combined-billing

PR: TBD

## What changed
A family with several children on autopay is now charged once, not once per child. When the dunning worker claims one family's rung, it also claims that parent's other rungs due at the same time and charges their total as one PaymentIntent. The parent gets one payment, one receipt naming every child, and, if the charge fails, one notice for the summed balance. A single due invoice, or an off-cycle invoice, is charged on its own exactly as before.

How it holds together:
- Only rungs for the same billing month and the same ladder step are grouped. Each claimed rung is stamped with a `charge_group_id`, used for metadata and the shared notice. The PaymentIntent key does not use it: it is `autopay-family:` plus a 32-character hash of the sorted `invoice_id:retry rung` pairs, then the total and the usual fee and route suffixes, so the same members on the same rungs always send the same key.
- A family charge that may already have gone through (a worker crash, a Stripe timeout, or any technical park) keeps its group. The retry takes back exactly those members and replays the same key, so Stripe returns the first charge. If any member has moved on (paid at the desk, settled, no longer autopaying), the rest park as `attempt_indeterminate` and are never charged as a smaller set or alone, until the webhook or reconciliation settles the first charge or the 24-hour L3 cap moves them to the single path. A rung that was charged alone and then parked retries alone and never joins a family.
- A family charge is only ever the whole set that was claimed. If any member is paid, voided, held by an open checkout or no longer autopaying, there is no family charge: on a first try each member is charged on its own, and on a retry they all park. So a retry can never grow or shrink the set and charge members again under a new key.
- Fix: an invoice held by an open checkout now parks as `checkout_session_open`. Before, comparing Mongo's naive hold timestamp with an aware clock raised, and the invoice parked as `charge_technical_failure` instead.
- Group size is capped so the comma-joined invoice ids fit Stripe's 500-character metadata value. A larger family splits by invoice id across charges.
- The settle, processing and failure webhooks loop over every invoice the PaymentIntent names. They validate the academy, parent and currency of all of them before writing anything, and quarantine the event if one does not match. A settled family payment allocates per invoice. If a sibling was paid another way while the debit settled, the surplus becomes account credit. A PaymentIntent that names a single `invoice_id`, including any made before this deploy, still settles on its bare `autopay-alloc:{pi}` key.
- A bank debit that comes back failed records each member's answer. The family gets one notice for the members still retrying, deduplicated by group across the members' separate settle passes, and it leaves out any sibling paid in the meantime. A member whose autopay is turned off gets its own final notice, so one member's notice never swallows another's. A family email names each child once ("Arjun, Maya and Dev").
- A bank return or lost dispute on a payment that settled several invoices reopens all of them and sends one notice per payment, not one per invoice. This also applies to balance checkouts.
- The pre-charge notice from the monthly run is grouped by parent and charge day: one email for siblings charged together.
- Late fees: one per family per billing month. A late fee on any of the parent's invoices for that month, automatic or hand-entered, suppresses the rest. That includes a fee line on a voided sibling: it still blocks a fee on the reissued invoice for that parent and month (intended). The automatic line's `source_id` is now `{parent_id}:{period}`, and migration 0232 makes it unique, so two overlapping passes write one fee. The losing pass puts that invoice's totals back.
- Reconciliation labels a repaired family autopay payment `stripe_autopay`, not `stripe_checkout`. A refund on a family payment with no allocations left is shared across its invoices, each up to its own total.

Capped ladders (L3 `technical_failure_capped`) keep their daily recheck and are never folded into a family charge.

## Deploy notes
- Do not deploy between Dec 29 and Jan 2: the 2027-01-01 billing-calendar switch must not share a deploy with this change.
- One migration, applied by the deploy pipeline's Migrate Production step: `0232_family_late_fee_unique_index`. It adds the partial unique index `late_fee_policy_family_period_unique` on `invoice_lines` (`academy_id`, `source_type`, `source_id`), filtered to `source_type == "late_fee_policy"` and `source_id > ""`. No manual step and no backfill. Existing policy lines carry `source_id == invoice_id`, so the build cannot meet a duplicate. In the dry-run and the release_command log, look for `0232_family_late_fee_unique_index` applied and no `migration_index_skipped_duplicates_present` warning. If that warning appears the migration fails the deploy: delete the surplus line or re-key its `source_id` (crediting it leaves the duplicate in place), then re-run.
- No new env var and no setting.
- Owner checks after deploy:
  - The next hourly dunning tick for a family with two autopaying children shows one Stripe PaymentIntent whose metadata has `invoice_ids` and `charge_group_id`, one ledger payment, and two allocations.
  - The parent receives one receipt naming both children.
  - Billing health shows no new quarantined Stripe events.

## Risk / rollback
High: this changes how autopay money is charged and settled. Every path has a real-Mongo contract test: one charge for two siblings, decline, ACH processing then success or failure with replay, stale-lease replay with a new sibling, a Stripe timeout after the charge was accepted (family and single), a partial retry after a crash, a lone parked charge, a sibling paid mid-flight, an unallocated family refund, a legacy single-invoice PaymentIntent, a family return, overlapping late-fee passes, the metadata cap split, and reconciliation. There is also a use-case test for another academy's invoice in a family's metadata.

Before reverting, let any in-flight family bank debit settle (up to about 5 business days). Old code reads only `invoice_id` from metadata, so it would not settle a family PaymentIntent. Reconciliation would repair it through its balance path (labelled `stripe_checkout`). Reverting leaves migration 0232's index in place. That is harmless, since old code writes `source_id == invoice_id`, which is unique per invoice. `charge_group_id` on dunning states is ignored by old code.
