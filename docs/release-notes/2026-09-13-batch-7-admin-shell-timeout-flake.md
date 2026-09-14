# Batch 7: widen legacy-URL redirect assertion timeouts

## What changed
- Fixes #637 — The `coach-payslip` → Payouts/Payslips tab and `pause-requests` → Requests/Pauses tab legacy-URL redirect assertions in `admin-shell.spec.ts` used Playwright's default 5s `toHaveURL` timeout, while every sibling redirect assertion in the same file already used a 30s timeout. Under CI load the redirect occasionally took longer than 5s, flaking the spec. Aligned both assertions to the existing 30_000ms precedent. No product code touched.

## Deploy notes
No migrations. No manual steps. Test-only change (Playwright spec timeout).

## Risk / rollback
Minimal risk: the change only widens an assertion timeout in an e2e spec to match the pattern already used elsewhere in the same file; it does not alter any application behavior. Rollback is reverting this PR.

PR: #815
