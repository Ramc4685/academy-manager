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
- No health or medical details beyond what the base demo seed already has,
  except k04, whose one fake allergy note is the state S49/S50/S63 test.

| Kit | State |
| --- | --- |
| k04 | Junior Beginners health answers: Sam Demo declared ("Peanut allergy, carries EpiPen", emergency contact Rosa Demo 555-0177), Alex Demo none declared, Mia Kitwell (new, `kit_k04_student_mia`) never answered. |
| k63 | Two class dates today: Junior Beginners from the top of the current hour (NOW) and the Junior Skills Clinic an hour later (NEXT). Run after k04. Re-running moves them to the current hour. |
| k00 | Seven extra families (14 kids) with past Saturday attendance. Keeps the `seed_*` ids of the original `seed_more.js` so it re-runs over a DB that already has them. |
| k01 | Demo Coach last month: one held class with no pay rate (unpaid) and one paid at a 50% rate. Casey Newcoach active with no held classes last month. |
| k03 | "Tuesday Intermediate" (`kit_k03_session_tue`): no price (fee null, not 0), two k00 kids enrolled. Run after k00. |
| k05 | Kiran Patel (`kit_k05_student_dev`; was "Dev Patel", which clashed with the base seed) transferred Saturday to Wednesday, with an Absent mark on Sat Nov 21 left in the old class. |
| k07 | A second academy `acad_fresh_local` at `fresh.localhost` whose only required live waiver is the untouched starter text. Owner `fresh.owner@example.com`: create that login in the Firebase emulator before signing in. |
| k27 | Kiran Patel (k05) also on the $80 Saturday class, ready to move to the unpriced k03 class. Run after k03 and k05. |
| k16 | (S25 part) the next future Saturday date cancelled with a reason. |
| k08 | This month on the Saturday class: two enrolled kids not yet invoiced, one paused and one free (NoCharge) enrollment, an overdue emailed invoice, an issued invoice never emailed, and an emailed invoice not yet due. |
| k15 | Demo Coach: approved payout period last month ($30 per held class), draft this month. Casey Newcoach named as the Wed clinic's assistant. Run after k01. Supersedes k01's unpaid last month (approves it, clears its unpaid classes), so retest S01 and S32 on `run.sh k00 k01` only. |
| k36 | Junior Beginners: Lena and Felix Schmidt not billed (scholarship, coach's child), so it reads "9 paying of 11 enrolled". Run after k00. |
| k06 | Casey Newcoach leads "Casey's Junior Starters" (a copy of the Wednesday clinic) with Tej Walkin, Noor Haddad and Owen Pryce enrolled and not placed on a level. Needs k01. Leave it out for Casey's empty first day. |
| k12 | Venue address, parking note and arrive-early minutes on the Saturday and Wednesday classes, plus the academy phone 555-0142 and office@example.com. Casey has no classes unless k06 ran, so leave k06 out to see her first-day empty state with the contact line. |
| k16 | Age ranges and levels on the Saturday (7–13, Mixed levels) and Wednesday (8–12, Beginner) classes. Ages on roster rows come from existing dates of birth (k00 and the base seed). |
| k02 | Free Wednesday clinic; for Rosa Alvarez (sign her up first) a PENDING_APPROVAL Lucia in it and a CHECKOUT_PENDING Mateo in Junior Beginners. |
| k09 | The busy parent owes this month's tuition for Sam and Alex with a $20.00 sibling discount on Alex ($140.00 due; the base seed's paid invoices reopened, their cash payments dropped). Last month stays paid in cash. |
| k10 | Alex Demo: next Saturday class (48h+ out) with no absence reported, and a late mark on the latest past class this month. |
| k11 | Alex Demo working on Split step (PRACTICING) with one private coach note and one ticked shared before S53 (no `shared_at`, so the parent does not see it until the coach shares it again). Partial: record the pass in the coach app during the re-test. |
| k44 | Casey Newcoach on no part of Tuesday Intermediate (k03), with future dates left to cancel and her email notifications on. Run after k01 and k03. |
| k46 | (S46) The demo academy's public page published with an address and an example.com refund link; both demo classes listed as Beginner, ages 8-12. |
| k68 | Two Level 1 lesson cards (`kit_k68_card_*`) on the demo academy's first active program, so "What we teach" opens with teaching content. For Casey's My week (no class today, one next week) run k01 and k15 (Wed clinic assistant) and leave k06 out. |
| k19 | Rosa Alvarez (sign her up first) has no phone, for the named profile gap. Partial: the broadcast-audience half is S69's. |
| k51 | (S51) Mila Quinn's PENDING_APPROVAL registration for Casey's class. Run after k01 and k06. |
