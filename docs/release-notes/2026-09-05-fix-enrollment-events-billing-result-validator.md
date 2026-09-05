# fix-enrollment-events-billing-result-validator

PR: #TBD

## What changed
Fixes #657. Admin **Remove / Withdraw / Pause / Move** enrollment returned
"Internal Server Error" in production (2026-09-04). Prod log + Sentry:

```
pymongo.errors.WriteError: Document failed validation
  billing_result: bsonType ['object','null'] — consideredValue
  'voided=0,autopay=disabled', consideredType 'string'
```

Root cause: schema/code mismatch. Migration 0133 declared
`enrollment_events.billing_result` as `["object","null"]`, but the domain model
(`EnrollmentLifecycleEvent.billing_result: str | None`) and every writer emit a
short string (`"voided=0,autopay=disabled"`, `"future_billing_stopped"`,
`"recorded"`). The validator only started biting when the backlog of migrations
was applied to prod by hand on 2026-09-02 (boot migrations are off, #629) — so
the failure looked new although the code had not changed.

- `backend/v2/migrations/0133_…`: `billing_result` → `["object","string","null"]`
  (single source of truth for fresh databases).
- `backend/v2/migrations/0165_enrollment_events_billing_result_string.py`:
  re-applies the corrected `enrollment_events` validator (`collMod`) on existing
  databases.
- `backend/v2/tests/unit/test_0165_…`: asserts the validator accepts the string
  the model declares, and that 0165 re-applies it.

## Deploy notes
**Prod needs migration 0165 applied by hand** (boot migrations are off). Until
then Remove/Withdraw/Pause/Move keep failing; each failed attempt rolled back
cleanly, so no partial data. Equivalent manual command: `collMod
enrollment_events` with the 0133 validator where `billing_result.bsonType =
["object","string","null"]`, `validationLevel: moderate`, `validationAction:
error`.

## Risk / rollback
Low — the validator becomes strictly more permissive on one field; no data is
rewritten. Rollback is re-applying the previous validator (which reintroduces
the bug).
