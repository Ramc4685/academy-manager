# stop-all-classes

PR: #702

## What changed

Admins can stop every class for a child or a family in one action, with one date, one reason and one outcome, honouring the configured default drop outcome and the owner gate on credit. A partial failure stays visible instead of being swallowed. A new leaving report shows who left, when, why and what it cost in monthly revenue.

## Deploy notes

No migration. Contains #697; merge PR #701 first. Adds one admin route, /admin/reports/leaving, registered in the QA inventory manifest. The family-level action calls the per-student endpoint once per child.

## Risk / rollback

The end-of-period outcome currently behaves like mid-month; a general admin-side deferred drop is a follow-up. Rollback by reverting.
