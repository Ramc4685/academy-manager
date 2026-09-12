# batch-1: billing invoice dedup

PR: #0

## What changed
- Fixes #723 — the monthly invoice run no longer bills a family twice for a month an admin already handled by hand. Previously `_invoice_has_consistent_lines` only recognized an existing invoice for the enrollment/period if its header matched the generator's own shape (subtotal gross, discount mirrored in `discount_cents`) and it carried at least one line. Hand-billed drafts built through the ledger store the subtotal net of the negative discount line and leave `discount_cents` at 0, and a draft created from "Create invoice" starts with no lines at all — both looked inconsistent to the old check, so a second invoice was minted for the same period.
- `_invoice_has_consistent_lines` now accepts either header convention (generator-shape or ledger-shape), and treats an all-zero line-less draft as already covering the period, while still rejecting an invoice whose stored totals disagree with its lines, or a line-less invoice with stale non-zero totals.

## Deploy notes
None. This is a read-time check only inside the monthly invoice generator — no stored documents change shape, no migration, no ledger invariant is touched.

## Risk / rollback
Risk: if the widened acceptance criteria are too permissive, a genuinely inconsistent invoice could be treated as "already covers the period" and skip regeneration, silently leaving a family unbilled for that period. This is mitigated by the explicit totals-vs-lines consistency check retained for both header shapes and for the all-zero line-less case (any non-zero stale total on a line-less draft still fails the check).
Rollback: revert this PR (single commit, read-only-check change) — no data cleanup required.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
