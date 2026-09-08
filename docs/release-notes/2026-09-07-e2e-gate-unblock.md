# e2e-gate-unblock

PR: #683

## What changed
Two test-only fixes that make the pre-push gate pass on `main` again: the tuition-discounts spec now stubs the two Billing-tab endpoints it was missing (they 500 and tripped its empty-console assertion), and the two bookmark-redirect tests arm `waitForURL` before navigating instead of asserting the URL afterwards, which stops them flaking. The gate counts a flake as a failure, so both were blocking every branch.

## Deploy notes
None. No production code, no migration, no env.

## Risk / rollback
No runtime risk — the changes are confined to `frontend/e2e/specs/`. If a redirect genuinely breaks, the armed `waitForURL` still fails the test after 30s. Roll back by reverting the PR.
