# Front desk roster tools and fixes

PR: TBD

## What changed
- The class roster's row menu offers Hold instead of Pause. Hold keeps the seat and stops billing until the agreed date; the backend pause endpoint is unchanged.
- Admins can tick several roster students and transfer them to another class in one step. Students who cannot move are named with the reason, and the form closes so the ones who moved can't be moved again. Two requests moving the same student at once can no longer both move them (this also covers the single transfer).
- Copy class starts a new class from an existing one, keeping every day of a multi-day class unless the admin changes them. Only an owner's copy keeps the price. Its active students can be copied only into a class with a different schedule (same days and times would enroll and bill them twice), never from a one-off class. Copied students are billed the new class's full price: fee overrides and discounts don't carry over. Students who could not be added are listed.
- Term rollover is deferred: classes have no term start or end dates yet, so there is nothing to roll forward.
- Parent makeup picker (#1037, #1041): the missed-class list comes from a new `GET /parent/makeups/candidates` route that uses the same eligibility check as submitting a request. Classes the student was marked present for, and classes the academy cancelled, are never offered or accepted. Siblings who missed the same class are listed separately, a denied request can be requested again, an absence notice is only needed when the academy requires one, and a failed load shows an error with Try again instead of an empty list.
- Supervisor teaching plan (#1044): a supervisor sees every class in the academy on the chosen date, matching Today. The plan names the date, and an empty past date no longer says "No sessions today".
- Admin timeline (#1052): a pause shows "resumes <date>" only for a scheduled return, "review <date>" for a review pause, and "review required" for older events with no date, instead of the pause's own start date.

## Deploy notes
Deploy backend and frontend together: the frontend calls the new bulk transfer, copy class and makeup candidates routes. No migration.

## Risk / rollback
Bulk transfer and copy class reuse the single transfer and enrollment use cases per student, so seat and billing rules are unchanged. Revert the PR to roll back; pause events written with the new resume or review date field stay readable by the old timeline.
