# self-cancel-release-seat

PR: #500

## What changed
Parent self-cancel now releases the reserved seat and emits
`EnrollmentCancelled` after the cancellation CAS succeeds, matching every other
cancellation path, so waitlist promotion actually fires and the monotonic
`reserved_seats` counter stops drifting upward. The seat is released only when
the CAS genuinely transitioned the enrollment, so a double self-cancel cannot
double-release. A lifecycle event is written too, so the admin timeline no
longer shows a promotion with no matching cancellation row — that row is
written best-effort (caught and logged), because it is ordered ahead of the
`EnrollmentCancelled` append and a cosmetic audit write must not be able to
suppress waitlist promotion on a cancel that has already committed.
Compensation runs
before the best-effort fee billing and is shielded, so a client disconnect
(`asyncio.CancelledError`, which bypasses `except Exception`) cannot skip it.

## Deploy notes
No migration ships here. Sessions that already leaked seats keep their inflated
`reserved_seats` — a one-off reconciliation that resets the counter to the count
of active enrollments per session is tracked separately and should be run
before relying on capacity numbers.

## Risk / rollback
`release_seat` and the outbox append now PROPAGATE rather than being
best-effort, so a failure in either returns 500 on an already-committed
cancellation. That is deliberate — a silently leaked seat is worse than a
visible error — but it is a new failure mode on a parent-facing path.
`asyncio.shield` is new to this backend: on client disconnect the shielded task
outlives the request, so a failure inside it surfaces as an asyncio task
exception rather than a request error. Roll back by reverting the merge commit;
seats released while it was live stay released, which is the correct state.
