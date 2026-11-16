# sibling-discount-badge

PR: TBD

## What changed
Admins can now see the automatic sibling discount before the invoice goes out. On the student page, each class shows "Sibling discount N% (automatic)", "Pays full price (sibling discount)", or "Manual discount kept" when a larger manual discount wins. The family billing page adds one line saying who pays full price and who is discounted this month. It is a read-only view (`GET /admin/families/{parent_id}/sibling-discount`) that runs the same decision the monthly invoice run uses, writes nothing and changes no money. Nothing shows while the sibling discount setting is off.

## Deploy notes
None. No migration, no env vars. It reads the existing `sibling_discount_decisions` collection (migration 0237).

## Risk / rollback
Read-only. If a badge is wrong, the invoice is still priced by the monthly run, which this change only refactors (it moves the decision step into `decide_sibling_discount`; the run still inserts the row exactly as before). Roll back by reverting the PR. Badge reads never page Sentry; an unreadable setting (only possible through a hand edit) shows as off, and the monthly run still pages for it. Each badge read rebuilds the family once per enrollment, which is fine at family sizes but is not cached.
