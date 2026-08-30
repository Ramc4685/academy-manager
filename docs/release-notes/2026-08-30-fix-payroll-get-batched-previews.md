# payroll-get-batched-previews

PR: #585

## What changed
`GET /admin/payroll/{month}` computed a payout preview separately for every
coach who did not yet have a persisted payout period, and every one of those
computations re-fetched the ENTIRE academy-month occurrence set (occurrences,
coach attendance, sessions, enrollments) because attribution to the paying
coach is an in-Python domain rule. Each computation also issued one
`coach_rates` lookup per matching occurrence. The page-load path therefore
scaled as O(coaches x occurrences): 10 ungenerated coaches over a 600-occurrence
month meant ~6000 occurrence docs deserialized plus dozens of sequential rate
`find_one`s per GET, all serial.

`ComputeCoachPayout` gains `execute_many`, which fetches the occurrence set
once and computes all requested coaches' statements from it; rate resolution
now loads each coach's rate timeline once (`list_for_coach`) and resolves the
effective rate in memory with the same semantics as the old per-occurrence
Mongo lookup (`effective_from <= t < effective_until`, most-recently-effective
wins, tz-normalized). The batch is surfaced through a new
`PayoutCalculator.calculate_many` finance port so `ListMonthlyPayroll` makes
one batched call for exactly the ungenerated coaches, and none when every
coach already has a period. Single-coach `execute` delegates to the same
shared body, so generation, recompute and individual statement paths are
byte-identical in output.

## Deploy notes
No migration, no new indexes, no API shape change — the endpoint returns the
same rows. Per request, Mongo work drops from one academy-month scan per
ungenerated coach to one scan total, and from one rate lookup per occurrence
to one timeline load per coach.

## Risk / rollback
The risky surface is the in-memory rate resolution replacing the Mongo
`find_for_coach_at` query; `test_execute_many_matches_individual_execute_results`
and the existing payout suite pin the equivalence, including the missing-rate,
rate-gap and naive-datetime paths. Displaced coaches (session_count 0) load no
rate timeline at all, preserving the old lazy behaviour. Roll back by
reverting the merge commit — no persisted state changes.
