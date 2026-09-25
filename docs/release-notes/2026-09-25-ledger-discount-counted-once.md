# Tuition discount is taken off a monthly invoice only once

PR: #TBD

## What changed

- Fixed a money bug: the tuition discount could be subtracted twice from a monthly invoice. The monthly generator writes a discounted month as a full-price tuition line, a negative discount line, and the same discount again in the invoice's `discount_cents`. `recompute_totals` added up the lines, which already included the discount line, and then subtracted `discount_cents` a second time. Any change that recomputed the invoice total therefore under-charged the family by the discount amount.
- Every recompute path had the bug: an ACH autopay discount line (on the first attempt and on every retry), the hourly late-fee pass, an admin-added line, an enrollment-move line, and `create_invoice` back-filling a missing line. For example, a $100 month with a $20 sibling discount and a $15 late fee showed $75 due instead of $95, which cost the family less than paying on time. The same month on ACH autopay was charged $57.50 instead of $77.50.
- `recompute_totals` now subtracts only the part of `discount_cents` that no `tuition_discount` line already covers. It also keeps the generator's full-price subtotal. Invoices without a discount line, and invoices whose discount is carried by a line with `discount_cents` 0, compute the same totals as before.
- Occurrence cancellation was not affected, because it already prices its credit from the invoice lines. A test now guards it.
- Added `scripts/ops/find_discount_double_count_invoices.js`, a read-only query that lists affected invoices and the amount each one was under-charged.

## Deploy notes

- No migration and no stored data is rewritten.
- Run `scripts/ops/find_discount_double_count_invoices.js` with a read-only user against prod BEFORE deploying, and keep the output. After deploy, an affected invoice that is still open moves to the correct higher total the next time something recomputes it, such as an autopay retry, a late fee, or an added line. The owner decides whether to re-bill or write off those amounts; the PR description sets out both options.

## Risk / rollback

- Medium risk: this touches invoice totals. After deploy, the balance on any still-open, already-affected invoice goes up by the discount amount the next time the invoice is recomputed. That amount is the correct charge, but the family has not been told about it.
- Rollback: revert this PR. That restores the double-counting, so revert only if the new totals are wrong. No data or index changes are involved.
