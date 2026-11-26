# tenant-collection-guard

PR: TBD

## What changed
Test and guard hardening only; no user-facing change. The static guard against
raw Mongo access now knows 55 more per-academy collections, including the
ledger payment, allocation and attempt rows, and a new test fails when code
names a collection that is not classified as tenant-owned, global or
platform/infra. Four `ledger_payments` call sites now show their tenant scope
at the call. New tests prove a parent cannot read another academy's
attendance or progress notes.

## Deploy notes
None. No migration or configuration change.

## Risk / rollback
Query filters are unchanged. Rollback is a plain revert.
