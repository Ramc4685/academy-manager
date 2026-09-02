# fix-digest-hourly-resend

PR: #631

Related: #629 (production has applied no migration after 0122), PR #558 (the
`>=` digest window that turned the missing index into hourly re-sends).

## What changed
Coach and parent daily digests can no longer be sent more than once per
recipient per day when the unique `(academy_id, recipient, digest_date)`
indexes from migrations 0125/0148 are absent.

Production symptom on 2026-09-02: every coach and parent received their daily
digest **once an hour from 12:00 CDT** for the rest of the day. PR #558 made
the scheduler re-run the digest on every hourly tick after the digest hour (so
a missed hour no longer loses the day) and relied on `try_claim` to refuse
recipients already handled that day. `try_claim` was an insert-first lock whose
only guard was `DuplicateKeyError` from the unique index — and production had
never built that index (`V2_RUN_MIGRATIONS_ON_BOOT=false`, registry stopped at
0122). With only `_id` indexed, every tick inserted a fresh `QUEUED` row and
sent again.

The claim (`digest_claim.claim_digest_send`, shared by both repositories) is
now correct with or without the index:

- it looks the day's row up **before** inserting, so a `sent`, `skipped` or
  in-flight row refuses the claim and a `failed` row still goes through the
  #435 retry ladder, exactly as before;
- after a successful insert it **verifies** that its row is the only one for
  the key and withdraws its own row if a concurrent claim also inserted. A
  caller holds the claim only if it saw itself alone, and two callers can
  never both see that — so at most one sends. If both observe the collision,
  both withdraw and nobody sends on that tick; the next hourly tick claims
  normally. With the index present the loser's insert raises
  `DuplicateKeyError` instead and the verify is a one-row indexed count.

Boot now checks that both unique indexes exist and, when either is missing,
logs `digest_claim_indexes_missing` at error level and raises a Sentry message.
It never blocks boot: the claim is safe without the indexes; they only make it
one round trip and turn a collision into a duplicate-key error.

## Deploy notes
No migration ships with this PR. **Production was already repaired by hand on
2026-09-02**: 185 coach and 2154 parent duplicate `coach_digest_sends` /
`parent_digest_sends` claim rows were deleted, and the two unique indexes from
migrations 0125 and 0148 were built and recorded in the migration registry.

After deploy, watch the boot logs for `digest_claim_indexes_missing`. It should
not appear in production; if it does, the index build did not stick — rerun
migrations 0125 and 0148 (or build them by hand). Digests still send exactly
once either way.

Production still has migrations 0123–0163 unapplied apart from those two; that
is tracked in the separate issue #629 and is not addressed here.

## Risk / rollback
Low. Each claim costs one extra indexed round trip (`find_one` before the
insert, `count_documents` after); claims run once per recipient per tick.
Behaviour with the index present is unchanged for every sequential case
covered by the existing retry tests, which run with the real migrations
installed. New tests run the real repositories on a bare mongomock database
(no migration applied) and pin: sent/skipped/fresh-queued rows are refused,
failed rows retry, admin test sends do not block the daily claim, three hourly
ticks send exactly once, and two interleaved claims yield at most one sender.

The only new behaviour under the index-less race is the "both withdraw" case,
which delays that recipient by one tick rather than sending twice; the
scheduler's `job_lease` already prevents two digest runs overlapping, so this
is a defence-in-depth path rather than an expected one.

Roll back by reverting the PR. With the indexes now present in production the
old insert-first claim is safe again; without them it re-sends hourly.
