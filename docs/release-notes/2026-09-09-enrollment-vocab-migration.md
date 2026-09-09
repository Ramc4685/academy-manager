# enrollment-vocab-migration

PR: #703

## What changed

Stored enrollment statuses move to the vocabulary the interface uses: withdrawn becomes dropped and cancelled-by-removal becomes deleted, across enrollments, lifecycle events, scheduled actions and student billing enrollments. Read paths accept both spellings for one release. Billing readers that enumerated the old words are routed through one normaliser, held rows gain their own bucket in the family enrollment counts, and every lifecycle event type now has a display label.

## Deploy notes

Migration 0171 renames existing rows. The status field has no schema enum, so no collMod is required. Production does not run migrations on boot — apply this one deliberately. Legacy paused rows are intentionally left as paused.

## Risk / rollback

The rollback direction is the risk: a previous release reading a renamed row would fail model validation, which is why the read path is tolerant of both spellings and the rename is confined to two values. Roll back by reverting the code first, then the data if needed.
