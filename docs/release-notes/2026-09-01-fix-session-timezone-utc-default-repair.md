# fix-session-timezone-utc-default-repair

PR: #615

## What changed
Adds migration `0160_session_timezone_utc_default_repair.py`, its contract
tests, and `scripts/prod/repair_session_timezones.py`.

The admin session form seeded its timezone field from `DEFAULT_TIMEZONE = "UTC"`
and only patched it once `GET /api/v2/admin/academy` resolved. When that patch
lost the race the client sent `timezone="UTC"`, and `CreateSession` stored a
6:00 PM America/Chicago class as `18:00Z` — 1:00 PM Chicago. The arithmetic was
always correct; the timezone was not. The code-side fix is separate and lives on
`fix/registration-prod-defects`; this change repairs the data only.

The bug is not display-only. Both occurrence generators key off
`doc["timezone"]` — billing's `_session_occurrences` and the catalog's
`synthesize_recurring_session_docs` — and `QuoteEnrollment` derives the whole
`BillingPeriod` from it.

The migration repairs only rows it can prove were mis-defaulted. All four must
hold: `timezone` is exactly `"UTC"`; the owning academy's timezone is present
and not UTC; the row is recurring so `start_at`/`end_at` are derived values that
can be recomputed; and the stored instants still match what `tzinfo=UTC` would
have written. An academy that is itself UTC, or has no timezone, makes the row
indeterminate — those are skipped and reported for a human decision, never
guessed at, because `MongoAcademyRepository.upsert_defaults` seeds academies
with `"UTC"` and that value is therefore not proof of intent. Instants are
re-derived per calendar date through `ZoneInfo`, so DST is correct across the
year; a fixed-offset shift would not be. Guard (4) also makes the pass
idempotent: once repaired to a non-UTC zone the wall clock no longer matches, so
a re-run skips the row.

Clean future `session_occurrences` are repaired the same way, mirroring
`composition/admin.py::_is_clean_future_occurrence`. Past, attended or
already-paid occurrences are history and are reported rather than rewritten.
`occurrence_id` embeds the local date and the literal `start_time`, neither of
which this repair changes, so ids stay stable and the update is in place.

Measured against production 2026-09-01 (read-only): one academy,
`acad_blno_badminton`, `timezone = "America/Chicago"`; 4 of 5 sessions carry
`timezone: "UTC"`; all four are recurring and pass the guard, and each session's
title states the intended local time, which independently corroborates the
repair. 13 future scheduled occurrences are in scope; 45 past ones are not.

No financial record is touched.

## Deploy notes
No new environment variable is required for the default behaviour, and no
manual step is needed for this deploy.

`up()` is **report-only** unless `SESSION_TZ_REPAIR_APPLY=1` is set. This is
deliberate: the boot migration runner would otherwise apply a
financially-material data rewrite unattended on the next deploy, and would then
record the version as applied — so a later flag flip would never re-trigger it
at boot. Deploying this PR therefore logs what needs repairing and writes
nothing.

The sanctioned way to actually apply it is
`scripts/prod/repair_session_timezones.py`, which calls the same `repair()`
directly and works regardless of what the `v2_migrations` registry records. It
is read-only by default, prints the blast radius and billing exposure, and
refuses `--apply` against a non-loopback Mongo URL unless
`--i-know-this-is-production` is also passed. Take a backup first.

Ship the code-side fix before applying the repair, otherwise a repaired row is
re-corrupted by the next session an admin creates.

## Risk / rollback
The deploy itself is inert: report-only, no writes, no schema change, no new
index. Risk is confined to a deliberate later `--apply` run.

The dominant risk in that run is a false positive — rewriting a row that is
genuinely UTC. That is what the four-part guard exists to prevent, and it is the
focus of the tests: a mis-defaulted row is fixed, a legitimately-UTC row is
untouched, an academy with no timezone is skipped and reported, a re-run changes
nothing, a dry run writes nothing, DST is not applied as a fixed offset,
non-matching instants and dated one-offs are skipped, and settled occurrences
are protected. Apply → re-apply was also exercised against a real Mongo with
seeded bad data; the second run changes zero rows.

Rollback of the code is deleting the three files; because `up()` writes nothing
by default, no data rollback is implied. If an `--apply` run has already
happened, reverting the data means re-stamping the affected sessions' `timezone`
and recomputing `start_at`/`end_at` under the old value — the before/after for
every changed row is logged at WARNING by `RowChange.describe()`, so the prior
state is recoverable from the run's own log.

Three issues surfaced during investigation and are deliberately **not** addressed
here: recurring sessions carry null `start_date`/`end_date`, so billing never
expands the series and sees at most one occurrence per period (likely a larger
correctness problem than the timezone, and independent of it); two of the four
affected sessions have zero future scheduled occurrences, since
`maintain_session_occurrences` only runs on create/edit and materialises 60 days;
and joining `payments`/`ledger_payments` on `enrollment_id` returned empty
despite CONSUMED monthly snapshots existing, which is contradictory and means
that join key is not trustworthy — it is not evidence that no invoices exist.
