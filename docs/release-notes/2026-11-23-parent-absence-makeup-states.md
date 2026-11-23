# parent-absence-makeup-states

PR: TBD

## What changed
Parents now see where each reported absence stands with makeups on Requests → Absences and on the Children class list: Reported, Makeup eligible (with a "Book a makeup" link that opens the Makeups tab with that class pre-selected), Makeup requested, Makeup booked (with the makeup class and date) or Makeup expired. The state is decided on the server by the same eligibility check a makeup request already runs; no makeup rules changed.

## Deploy notes
None. No migrations, env vars or manual steps. `GET /api/v2/parent/absences` gains an optional `makeup` field and the child schedule gains `absence_makeup` on reported dates; older clients ignore them.

## Risk / rollback
Read-only: no writes, credits or billing are touched. If the state lookup fails the absence list still loads without a state. Roll back by reverting the PR.
