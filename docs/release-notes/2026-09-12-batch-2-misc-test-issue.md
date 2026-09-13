# Batch 2: one enrollment status vocabulary with derived predicates

## What changed

- Fixes #642 — the enrollment domain (`backend/v2/contexts/enrollment/domain/models.py`) now owns a single closed status vocabulary (`ENROLLMENT_STATUSES`) plus derived predicate frozensets: `SEAT_HOLDING`/`SEATLESS` (pre-existing, kept), `LIVE`, `NON_TERMINAL`, `TERMINAL`, `BILLABLE`, `ROSTER_VISIBLE`, `ATTENDANCE_VISIBLE`, `ACTIVE_OR_PAUSED`, and `DROPPED_SPELLINGS`/`DELETED_SPELLINGS`. Each predicate answers exactly one question about a row (does it hold a seat, is it billable, does it show on the roster, etc.), replacing 18 hand-rolled status-set literals previously scattered across `admin_writes`, `cancel_session_occurrence`, `get_session_roster`, `process_scheduled_cancellation_actions`, and the Mongo enrollment repo/writer/student repo. No behavior change — the migrated call sites use the same status members as before, now sourced from one place.
- A new structural test bans status-set literals under `contexts/enrollment/` outside `domain/`, so future call sites are forced to use the shared predicates instead of re-deriving their own meaning for a status like "paused".
- Migration 0175 makes the vocabulary a rule at rest: a `validationLevel: moderate` `$jsonSchema` enum on the enrollment collection that admits both legacy status spellings and the `__deleting__` CAS sentinel.

## Deploy notes

- Includes Mongo migration `0175_enrollment_status_enum_validator.py`. It only adds a moderate-level `$jsonSchema` validator (enum constraint) to the enrollment collection — it does not rewrite any documents, so it is a schema-only change and is safe to run against production data as-is. No manual steps or environment variables required.

## Risk / rollback

- Low risk: the predicate frozensets are structurally equivalent to the status sets they replace (same members), so behavior is unchanged; the added structural test and Mongo validator are net-new guardrails, not behavior changes.
- Rollback: revert this PR. The Mongo validator migration would need its own down-migration or manual `collMod` to drop the validator if a rollback is required after the migration has run in an environment; no data is mutated so there is no data-recovery concern.

PR: #766
