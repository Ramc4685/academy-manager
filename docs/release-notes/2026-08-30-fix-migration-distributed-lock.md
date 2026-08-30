# migration-distributed-lock

PR: #581

## What changed
Boot-time migrations (`V2_RUN_MIGRATIONS_ON_BOOT=true` on every prod
machine) ran with no distributed lock and no unique index on the
`v2_migrations` registry, so two machines booting in the same window — a
scale-out to 2+ machines, or a bluegreen deploy overlapping a
crash-restart — both read the applied set, executed the same pending
data backfills interleaved, and both inserted duplicate registry rows
(`#507`). `run_pending_migrations` now claims the same Mongo-backed
`job_lease` the scheduler uses (`v2_boot_migrations`, 15-minute TTL)
before running; a boot that loses the race polls until the holder
releases (or a stale lease from a crashed holder expires) and then
re-reads the registry, so it only proceeds once migrations are applied.
Version recording became an upsert keyed on `version`, and new migration
`0156_migrations_registry_unique_index` dedupes any historical duplicate
registry rows (keeping the earliest `applied_at`) and adds a unique
index on `v2_migrations.version` as defense in depth. New contract tests
cover the lease wait, stale-lease takeover, lost-race recording, and the
0156 dedupe.

## Deploy notes
No configuration changes. On first boot after deploy, migration 0156
runs once (under the new lock), dedupes the registry, and builds the
unique index — both are fast on a collection this small. During a
bluegreen deploy the new machine may briefly wait on the lease while
another machine finishes; boot logs show "Migrations lease held by
another machine" while polling.

## Risk / rollback
The loser now blocks boot until the winner finishes or the 15-minute
lease expires; a genuinely wedged migration holder delays — but no
longer duplicates — the second machine's boot, which is the safe
direction for billing backfills. If the holder crashes mid-run the lease
expires and the next boot resumes the idempotent migrations from the
registry. Rollback: reverting the merge restores the old lockless
runner; the unique index and deduped registry rows are harmless to older
code (it only ever inserts genuinely new versions in single-machine
operation).
