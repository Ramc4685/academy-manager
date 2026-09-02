# feat-enrollment-comms-roster-add-and-notifications

PR: #620

## What changed
Four issues that all land on the same enrollment surface: the admin
add-to-roster path (`#610`), a per-session communication pack and parent
welcome email (`#613`), coach/owner/parent lifecycle notifications
(`#612`), and in-app session announcements (`#614`).

`#610` was reported as a raw 500 on Enroll with the student never added.
The issue blamed an unmapped `CapacityExceeded`, which is wrong —
that error subclasses `DomainError` with `status_code = 409` and
`register_exception_handlers` already translates it. The reporter saw
Starlette's plain-text 500 body, so it was an uncaught exception.
Replaying the four writes against a live Mongo with migrations 0010,
0132, 0147 and 0150 reconstructed found three distinct defects.

The 500 itself is migration `0010`'s `_unique_v2_id`, which builds
`student_id_unique` on the bare `student_id` — globally unique rather
than `(academy_id, student_id)` — while every writer filters
tenant-scoped. A students doc under a different academy makes the
filter miss, the upsert degrades to an insert, and the global index
rejects it with E11000. That is why this only appeared on the new
`blno-badminton` tenant and not on the original one. Migration `0162`
rescopes the index per academy.

The second defect is why the session stayed broken afterwards: the seat
was reserved before the three writes that can throw, nothing released it
on failure, and `release_seat` carries an `$expr > 0` floor, so the
drift was one-way and never self-healed. Reservation is now
all-or-nothing, with `enrollments.create` as the explicit point of no
return — a failed *audit* write no longer releases a seat underneath a
live enrollment, which would have left ten active rows against
`reserved_seats == 9` and admitted an eleventh student.

The third defect is silent and had nothing to do with the 500:
`MongoStudentWriter.upsert` wrote the full model with `$set`, so
re-adding an existing student nulled `date_of_birth`, both emergency
contacts, `medical_notes` and `student_user_id`. Nulling the last one
breaks that student's login without raising, because migration 0150's
partial index only covers `$type: "string"`. The roster path now uses
`ensure_exists` (`$setOnInsert` only); `upsert` is retained for
`admin_registration_review`, which legitimately owns the full profile.

A refused reservation is now diagnosed instead of blanket-reported as
"session full": `SessionNotFound`, `SessionNotEnrollable`,
`CapacityExceeded` and `SeatCounterDrift`, each carrying the real
counts. A repeat add is also refused up front — there is no unique
`(session, student)` index, so it was previously creating a second
active enrollment in silence.

`#613` adds seven optional session fields and one parent welcome email
with conditional sections. `_build_admin_session_rows` is a hand-written
projection that was already dropping `amount_cents`, which is `#609`;
that is fixed here as a drive-by, and a structural test now fails if any
`AdminSessionView` field is missing from the projection so the bug class
cannot recur silently. `whatsapp_group_link` is validated at the request
boundary and again on the frozen domain model, because
`model_copy(update=...)` bypasses pydantic validators and the admin edit
path would otherwise have been the only unchecked writer.

`#612` wires one notification pipeline over approval, add-to-roster,
waitlist promotion, transfer and withdrawal. Staff alerts use a new
unsubscribable `NOTIFICATION` category; the parent's waitlist-promotion
mail stays transactional. It shares one send pipeline and one time
formatter with `#613`, so the two emails cannot disagree about a class
time. A notification failure never fails the enrollment write.

`#614` adds session announcements. `MongoMessageRepository.for_recipient`
previously returned every `kind: "announcement"` document to every
parent in the academy with no per-recipient clause, and `mark_read`
repeated that predicate inline — the duplication was the bug. Both now
call one shared visibility filter whose session list is keyword-only
with no default, and admin's unrestricted read is a separately named
method, so no future call site can fail open by omission.

## Deploy notes
Two migrations. `0161_session_announcements` adds an index for the
scoped announcement query. `0162_student_id_unique_per_academy` drops
the globally-unique `student_id_unique` in favour of an
`(academy_id, student_id)` index; it aborts loudly if duplicate pairs
already exist, but that scan should be run against production **before**
the deploy rather than discovered during it. Both were verified against
mongomock only and have not been run against a real MongoDB.

Existing `reserved_seats` drift is **not** repaired by this change. The
compensating release only prevents future leaks, so sessions already
inflated stay inflated and will now surface as `SeatCounterDrift` 409s
instead of succeeding-then-failing. Expect a burst of those on deploy;
they are pre-existing corruption becoming visible, not a regression.
Reconciliation is a deliberate ops action.

Pre-existing duplicate active enrollments for the same
`(session, student)` will now be refused. Correct, but it can read as a
regression; the 409 names the existing `enrollment_id` so an admin can
cancel it first. No unique `(session, student)` index was added — that
is unsafe until those duplicates are cleaned up.

Roster alerts are ON for every academy as soon as this deploys, with the
recipient-level `NOTIFICATION` opt-out as the only brake. An
academy-level default-off switch is the safer first release and is a
self-contained follow-up; decide before promoting to production.

Outstanding data repair, unrelated to whether this merges: any student
added to a roster while the clobber was live has null date of birth,
emergency contacts and medical notes, and any who had a login has a null
`student_user_id` and cannot sign in. Audit `students` for null
`student_user_id` cross-checked against identity users. Values may be
unrecoverable.

No environment variables and no manual steps beyond the above.

## Risk / rollback
The riskiest surface is `#610`, because it changes seat accounting on a
path that money and capacity both depend on. It is covered by tests
asserting the counter after a duplicate add, after a mid-write failure,
after a genuinely full session, and after a failed audit write, plus a
test that an existing student's profile survives a re-add. Every path
through the new `execute` was walked in review specifically for
double-release, which would be as bad as the leak it fixes.

`#614` carries the only new information-disclosure surface, and it
closes one rather than opening one: session announcements are scoped at
read time to the parent's active enrollments, pinned by a test that an
unenrolled parent cannot see a session announcement through
`GET /parent/messages` while still receiving academy-wide ones. A
sibling test proves marking an invisible message read returns 200 but
does not land in `read_by`, so the endpoint is not an existence oracle.
One consequence to expect at the support desk: a family that withdraws
loses portal access to announcements they were already emailed.

Urgent announcement fan-out has no idempotency key and writes no
delivery rows, because it reuses the `#612`/`#613` send port rather than
`SendCampaign`. A retried or double-clicked POST emails the roster
twice. That is the known upgrade path if duplicates appear.

Reverting the merge restores the previous behaviour for all four
changes. The two migrations are not reverted by that: `0162`'s index is
strictly more permissive than the one it replaces, so leaving it in
place is safe, and `0161`'s index is inert once the routes are gone.
Nothing persisted needs cleanup on rollback — announcements and emails
already sent simply stop being produced.
