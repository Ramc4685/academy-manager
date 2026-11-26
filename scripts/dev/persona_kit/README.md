# Persona kit seeds

Small mongosh scripts that put the Demo Academy into the states the persona
usability re-tests need (docs/qa/2026-11-26-persona-usability/plan/plan.json,
`seed_plan.items`). Each `kNN_<slug>.js` is one kit item.

**Local only.** `run.sh` refuses any host but `127.0.0.1` or `localhost`.
Never wire these into CI, a `release_command`, a migration or a deploy.

```bash
scripts/dev/persona_kit/run.sh            # every kit, in file order
scripts/dev/persona_kit/run.sh k01 k05    # a subset
MONGO_URL=mongodb://localhost:27018 DB_NAME=other scripts/dev/persona_kit/run.sh
```

Defaults: `MONGO_URL=mongodb://127.0.0.1:27017`, `DB_NAME=academy_manager_local`.
Run the base demo seed first (`scripts/local_test_stack.sh fresh`).

Rules for a new kit:

- Idempotent: `updateOne(..., {upsert: true})` keyed on fixed `kit_*` ids, so
  running twice changes nothing. Use `$setOnInsert` for rows another script or
  the app may also own.
- Fake people only: made-up names, `@example.com` emails, 555 phone numbers.
- No health or medical details beyond what the base demo seed already has.

| Kit | State |
| --- | --- |
| k00 | Seven extra families (14 kids) with past Saturday attendance. Keeps the `seed_*` ids of the original `seed_more.js` so it re-runs over a DB that already has them. |
| k01 | Demo Coach last month: one held class with no pay rate (unpaid) and one paid at a 50% rate. Casey Newcoach active with no held classes last month. |
| k03 | "Tuesday Intermediate" (`kit_k03_session_tue`): no price (fee null, not 0), two k00 kids enrolled. Run after k00. |
| k05 | Dev Patel (`kit_k05_student_dev`) transferred Saturday to Wednesday, with an Absent mark on Sat Nov 21 left in the old class. |
| k07 | A second academy `acad_fresh_local` at `fresh.localhost` whose only required live waiver is the untouched starter text. Owner `fresh.owner@example.com`: create that login in the Firebase emulator before signing in. |
| k27 | Dev Patel (k05) also on the $80 Saturday class, ready to move to the unpriced k03 class. Run after k03 and k05. |
| k16 | (S25 part) the next future Saturday date cancelled with a reason. |
