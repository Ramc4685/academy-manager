# dunning-scan-index

PR: #583

## What changed
The hourly autopay dunning tick's `prepare_due_states` ran an unindexed
invoice query (academy + status + due-date with an in-memory sort) and
paid one `student_billing_enrollments` lookup per open invoice on every
tick, growing with unpaid-invoice backlog (`#513`). Migration
`0156_dunning_scan_invoice_index` adds a compound `invoices` index
`(academy_id, status, due_date, invoice_id)`, partial on
`balance_due_cents > 0`, so the scan's filter and sort are index-served.
The scan itself now streams invoices in pages of 200 with a projection,
dropping invoices that already hold a dunning state via one `$in` query
per page and resolving autopay eligibility with one batched enrollment
query per page instead of a per-invoice `find_one`. State creation keeps
the race-safe `$setOnInsert` upsert and the existing
overfetch-past-existing-rows limit semantics; the loop exits as soon as
the creation limit is reached mid-stream.

## Deploy notes
Migration 0156 runs automatically at boot and builds the partial index;
on current data volumes the foreground build is instantaneous. No
configuration changes, no behaviour change to which invoices enter
dunning or when.

## Risk / rollback
Low: dunning selection semantics are pinned by the existing contract
suite plus new tests counting the per-page query budget and exercising
multi-page limit exits. Rollback is reverting the PR — the index is
additive and harmless to leave in place.
