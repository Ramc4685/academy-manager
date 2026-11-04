# batch-5-admin-backend-consolidated

PR: #799

## What changed

- Fixes #449 — Adds the missing bulk-invite UI for the admin users directory. A "Bulk invite parents" button (parent tab and the unfiltered directory) opens a dialog where an admin pastes `email, name` lines or picks a CSV; rows are parsed, validated, lowercased and de-duplicated in the browser, previewed with a live count, then POSTed to the existing `/admin/users/bulk-invite` endpoint. The result step shows the per-row created/skipped/failed table plus a "Retry N failed" button. Malformed rows and batches over the backend's 100-row cap never leave the browser. Backend untouched — no route, DTO, or schema change.
- Fixes #618 — Manual and Stripe-checkout payments on `/admin/payments` no longer show "Unassigned". Student-name resolution in `list_payments_recent` now runs over all rows (not just invoice rows) in decision order: the row's own `student_id`, else the allocated invoice's student, else the parent's only child, else the parent's name with a "(family payment)" suffix. Rows that already carry a resolved name are never overwritten. The resolver lives in a new `composition/payment_student_resolver.py` (admin.py was at its wiring line budget). No frontend change.
- Fixes #539 — Added an audit trail for coach attendance payroll edits: `MongoCoachAttendanceAuditLogRepository` appends one entry per edit that actually changes status or `rate_override_minor` (creation and no-op resubmits are not audited).
- Fixes #694 — Fixed orphaned make-up/trial roster rows on coach rosters. Added a defensive read filter in `GetOccurrenceRoster` that drops one-time rows whose occurrence no longer exists or is cancelled, a session-wide sweep (`remove_future_for_session`) on whole-session cancel (make-up/trial students hold no enrollment and were skipped by the per-enrolled-student cleanup), and `occurrence_roster_entries` pruning in both branches of `maintain_session_occurrences`. A one-off backfill migration (0180) cleans up rows already stranded in production.
- Fixes #468 — Audit-log rows now name the real actor: the read path batch-joins `users` plus the academy's `academy_memberships` once per page and returns `actor_type`/`actor_role`/`actor_name`, replacing the hardcoded "Admin or system actor" label. Login events are also now recorded onto the audit trail from the auth-claims load path (best-effort, never blocks sign-in).
- Fixes #471 — Implemented per-coach "marked within 24h" attendance compliance (gap (a) from the issue's re-verification): a `MarkedWithin24hReader` port + `MongoComplianceReader` adapter, wired into `GetCoachUtilization` as an optional `compliance_reader` producing `compliance_within_24h_rate`, rendered as a new "Marked within 24h" column in the coach utilization panel. Gaps (b) per-student 8-week trend/at-risk flag and (c) no-shows-this-week panel are NOT implemented — issue #471 stays open for those.
- Fixes #554 — Built the void half of the attendance correction workflow. Attendance gains an additive "voided" status; an admin-only `VoidAttendance` use case annuls a mark at any time with a mandatory reason and emits `Coaching.AttendanceVoided`. Admin BFF gets `PATCH /session-occurrences/{id}/attendance/{student_id}/void` plus a read-back; the session-detail class-dates table offers "Attendance" → a reason-required Void dialog. A voided mark counts as unmarked everywhere (payroll and attendance-rate readers name their counted statuses as explicit constants, test-pinned). Parents see the row labelled "Removed". The coach self-correction window drops from 48h to 24h.
- Fixes #748 — `GET /admin/enrollments/{id}/events` was an unbounded Mongo scan materializing full event history per request (503 risk on the Cloudflare Worker's CPU/memory budget for long-lived enrollments). Added `limit` (default 100, max 500) + cursor pagination on `(occurred_at, _id)`, sort order changed to most-recent-first, response now carries `next_cursor`. The only frontend consumer (`EnrollmentHistory` badge) now requests `limit=1`; `listEnrollmentEvents` in `admin.ts` gained optional `{limit, cursor}` params for a future full-history view. Not tracked in the audit inventory manifest, so no manifest update was needed.
- Also includes a small mypy-baseline cleanup pass (no behavior change): explicit Optional-narrowing in the #539 audit branch, `dict[str, Any]`/`AsyncIOMotorDatabase[Any]` type-argument fixes in the #468 and #554 wiring, and a `Sequence` return type on `MarkedWithin24hReader.compliance_for_periods` so the concrete reader satisfies the protocol covariantly.

## Deploy notes

Includes migrations:
- `backend/v2/migrations/0179_coach_attendance_audit_log.py` — indexes for the new `coach_attendance_audit_log` collection (#539).
- `backend/v2/migrations/0180_backfill_orphaned_occurrence_roster_entries.py` — one-off backfill pruning stranded make-up/trial `occurrence_roster_entries` rows (#694).

Confirm `V2_RUN_MIGRATIONS_ON_BOOT` covers these, or run them manually per AGENTS.md before/at deploy. No manual env var or config changes.

## Risk / rollback

Most of this batch is additive (new audit trails, a new void endpoint/status, a new UI dialog, pagination on a read-only endpoint) and covered by existing/added unit and route tests. The highest-risk items are #618 (changes which payments display which student name — de-dup and precedence order are tested) and #694 (roster read-filter + a destructive backfill migration limited to already-orphaned rows with no live enrollment). If anything regresses in prod, revert this PR's merge commit; migration 0179 (index-only) and 0180 (backfill of already-orphaned data) do not need a separate rollback.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
