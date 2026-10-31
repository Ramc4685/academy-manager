# chore-renumber-migration-0190

PR: #885

## What changed

- Two pull requests merged on the same day (#879 and #882) each added a migration numbered `0189`. The one from #879, `0189_type_partial_indexes_planner_usable`, is renumbered to `0190_type_partial_indexes_planner_usable`. It had not been applied to production or any shared database, so this is a pure rename: the migration's behaviour is unchanged.
- The guard test from #878 that stops new `$type`-filtered partial indexes now allows exactly one survivor, `message_deliveries.provider_message_id`, which is global on purpose. Its old allowlist still named eight indexes that #849 has since replaced.
- The release note for #879 now gives the right migration number in its deploy steps.

## Deploy notes

Backend-only, no behaviour change. After the deploy, apply `0190` by hand via `fly ssh console -a courtmastr-academy-api` and `backend.v2.migrations.run_pending_migrations` (#629), exactly as the #879 note describes. If anyone applied `0189_type_partial_indexes_planner_usable` to a local or staging database before this lands, `0190` will run once more there; it is idempotent and makes no changes on a second pass. No env vars.

## Risk / rollback

Minimal. The renumbered migration was re-verified against a real MongoDB with all 106 earlier migrations replayed first: all 25 indexes keep their name, key and uniqueness, end on the `$gt: ""` filter, leave no `__swap` twin, and a run interrupted mid-swap resumes cleanly. To roll back, revert this PR's merge commit before `0190` is applied.
