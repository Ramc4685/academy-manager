# test-attempt-validation

PR: #578

## What changed
`RecordTestAttempt` (coach and admin "record skill test" POST) accepted
`success_count > attempts_count`, so a request with `attempts_count=1,
success_count=5` recorded a 500% score and force-passed the skill regardless
of the skill's `pass_threshold_pct` and the `coach_override_allowed` gate,
feeding level-completion and certificate eligibility with bogus data. The
command and both route bodies now reject `success_count > attempts_count`
with a 422 before the use case runs.

The endpoint also had no idempotency key — unlike attendance marking — so an
offline-sync or network retry inserted a duplicate `TestAttempt` row and
re-emitted `SkillTestAttempted`/`SkillPassed`/`LevelCompleted` outbox events.
The request body now takes an optional client-generated `mutation_id`; when
present, the use case dedupes on `record_test_attempt:{mutation_id}` through
the shared `@idempotent` store (same pattern as MarkAttendance) and a retry
returns the original result. Requests without a `mutation_id` behave exactly
as before.

## Deploy notes
None. Uses the existing `idempotency_keys` collection (TTL index from
migration P0-16); no new migration, no new environment configuration. The
frontend API client types gained an optional `mutation_id` field only —
existing callers are unaffected.

## Risk / rollback
Low. The validator only rejects requests that were previously recording
impossible >100% scores; legitimate submissions (`success_count <=
attempts_count`) are untouched. Idempotency is opt-in per request via
`mutation_id`, so no existing client behavior changes. Rollback is a straight
revert; no data migration to unwind.
