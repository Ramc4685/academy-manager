# fix-level-up-lifecycle

PR: #TBD

## What changed
The level-up queue and its approval now respect enrollment lifecycle (issue #673). A
student recommended while enrolled and then withdrawn or cancelled used to sit in the
admin **Level-ups** tab indefinitely and could be approved — issuing a certificate and
advancing a level for a student who no longer attends. Now:

- `GET /api/v2/admin/level-up-queue` annotates every row with `enrollment_active`
  (one batch read over `enrollments`, active-or-paused = live, the same predicate the
  coach passport uses since #651). Withdrawn rows stay listed so the admin can reject
  them; the tab shows a **Withdrawn** chip and disables Approve with a tooltip.
- `POST /api/v2/admin/level-up/{rec_id}/approve` refuses a student with no live
  enrollment with `409 StudentProgress.EnrollmentEnded` before any write. Reject is
  still allowed. `RecommendLevelUp` gets the same guard behind the coach route's 404.
- The `Enrollment.EnrollmentCancelled` handler now also expires that student's pending
  recommendations once they have no active-or-paused enrollment left (a student who
  drops one of two sessions, or a paused student whose seat was handed on, is left
  alone). Expired rows are closed as `REJECTED` with `rejection_reason =
  "enrollment_ended"` and `reviewed_by = "system:enrollment_ended"` — no new status, so
  the migration-0133 validator and every existing reader are untouched.

Code: new `EnrollmentStatusLookup` port in
`contexts/student_progress/application/ports.py`, adapted in the new
`composition/level_up_lifecycle.py` (kept out of `composition/admin.py`, which is at its
line cap); `contexts/student_progress/application/use_cases/expire_level_up_recommendations.py`;
`frontend/components/admin/admissions/LevelUpsTab.tsx` + `level-up-review.ts`.
The coach passport (`frontend/app/(coach)/coach/students/[studentId]/passport/page.tsx`)
names the ended enrollment when the recommend tap hits the same 409 instead of the
generic "Failed to submit recommendation.", and `admin-level-ups-lifecycle.spec.ts` now
also runs on the `chromium-desktop` Playwright project.

## Deploy notes
None. No migration (no new status, no new field on a validated collection — the queue's
`enrollment_active` is computed, not stored), no env vars, no new endpoint. The
handler's new dependency is wired in `compose_parent` alongside the existing
`HandlerDeps`; a `HandlerDeps` built without it (older wiring) simply skips the expiry.
Existing stale rows in prod are not backfilled: they surface with the Withdrawn chip
and approve is refused; an admin rejects them from the tab.

## Risk / rollback
The approve guard reads `enrollments` by `student_id` + status; a student whose only
enrollment rows are `cancelled`/`withdrawn` is refused, `active`/`paused` pass. If the
enrollment data is wrong for a student the admin sees a 409 with the student id and
can reject or fix the enrollment — no silent certificate. The expiry runs before the
waitlist promotion inside the same handler, in its own try/except: its failure is logged,
not raised, so a level-up hiccup never replays a seat promotion. Rollback is reverting the PR; expired
rows stay `REJECTED` (reason `enrollment_ended`) and would need a manual status reset if
the expiry was wrong for someone. The approve guard is check-then-act: a withdrawal that
commits in the few milliseconds between the enrollment read and the approval write can
still certify that student — accepted as-is given the window, and the certificate is
visible in the student's timeline if it ever needs a manual revoke.
