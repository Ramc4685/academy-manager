# admin-shell-message-stubs-and-shard-guard

PR: #564

## What changed
Two hardening fixes to the e2e/test tooling. First, `#498` stubbed the
persona-shell message polls in six specs, but `admin-shell.spec.ts` kept its
own local `stubCoachBff`/`stubParentBff` helpers that never stubbed
`/api/v2/{coach,parent}/messages` — so the "coach smoke route mounts" and
"parent smoke route mounts" clean-console specs (and the shared logout spec
using the same helpers) could still flake when the unstubbed inbox poll
500ed. Both helpers now call the shared `stubCoachMessages`/
`stubParentMessages` fixtures. Second, the local pre-push gate's
`for project in $(e2e_projects)` loop discarded the function's exit code: a
broken Playwright config path degraded to running zero e2e shards while the
gate still exited 0. The shard list now comes from `e2e_shard_list`, which
hard-fails on a missing config or an empty project list, and
`pre-push-checks.sh` captures it up front and aborts loudly on error, with
three new regression cases in `pre-push-checks.test.sh`.

## Deploy notes
None. Test fixtures and local developer tooling only — no production code,
no migration, no config change.

## Risk / rollback
Zero production risk. The only behaviour change developers can see is that a
broken or empty Playwright project list now fails the pre-push gate instead
of silently skipping every e2e shard — which is the point. Roll back by
reverting the merge commit.
