# Lifecycle completeness: orphan matrix, uncovered gaps, derivation spec (2026-09-12)

Follow-up to `2026-09-12-ui-persona-lifecycle-audit.md`. Thirteen agents inventoried every persisted entity, traced creators, transitions, terminal states and dependents, then cross-checked against the batch-3b/3c plan (#772 to #778). Every high-risk row was re-verified by the cross-check agent opening the cited file.

## 1. Orphan matrix (38 rows: 26 high, 8 medium, 4 low)

| Risk | Parent entity | Terminal event | Dependent | Today | Required | Evidence |
|---|---|---|---|---|---|---|
| high | Enrollment | dropped via WithdrawEnrollment / StopAllClasses (paused pre-image) | waitlist_entries — the paused student's own 'waiting' reclaim row | Row stays 'waiting'. WithdrawEnrollment has no waitlist dependency; next freed seat auto-promotes the departed student into a NEW active enrollment and emails 'seat opened'. | Withdraw/Cancel/StopAll/scheduled-cancel of a paused row must call remove_waiting_for_session_student (same as ResumeEnrollment does). | backend/v2/contexts/enrollment/application/use_cases/admin_writes.py:1712-1735 (Pause adds), :1928-1953 ctor has no self._waitlist, :2172-2173 (only Resume removes); promote_from_waitlist.py:141-192 only short-circuits on an existing active row (verified) |
| high | Enrollment | dropped / deleted / cancelled / session_cancelled / hold reclaimed | pause_requests (pending) | No handling exists: no code path outside pause_requests.py touches pause_requests (grep verified). Pending rows stay in list_pending, /admin/pause-requests, PausesTab and the dashboard count forever; approving one later re-pauses a terminal row because PauseEnrollment has no LIVE guard. | Decline/expire pending pause_requests on every terminal transition (reason enrollment_ended); PauseEnrollment must refuse non-LIVE rows; repo approve/decline must CAS on status=='pending'. | backend/v2/contexts/enrollment/infrastructure/mongo_pause_request_repo.py:89-128 (verified: no status guard on approve/decline); admin_writes.py:1686-1706 (verified: only 'paused' and 'held' checked) |
| high | Enrollment | reclaim_pending → dropped via finalize_reclaim (hold reclaimed / expired / orphaned) | scheduled_enrollment_actions, enrollment_billing_deferrals (admin_hold), session_occurrence_roster rows, outbox EnrollmentCancelled (level-up expiry + waitlist promotion), staff roster alert, pause_requests | finalize_reclaim does only release_seat, billing_sync('dropped'), enrollment_events.record and notifier.hold_reclaimed. Nothing else the admin Drop path does. | Route hold-driven drops through the same post-terminal bundle as WithdrawEnrollment (retire actions, close deferrals, drop future roster, emit EnrollmentCancelled, staff alert). | backend/v2/contexts/enrollment/application/seat_broker.py:192-290 (verified keyword scan: no outbox/scheduled/deferral/occurrence_roster/waitlist); admin_writes.py:1999-2060 for the full bundle |
| high | Enrollment | paused → active via outbox waitlist promotion (parent composition) | enrollment_billing_deferrals, student_billing_enrollments.autopay_enrollment_status, monthly invoice generation | composition/parent.py PromoteFromWaitlist is built without resume= and without seat_broker; a paused head-of-queue student is flipped by bare update_status: no billing_sync 'resumed', autopay stays paused, admin_pause deferral stays active so invoices keep being skipped while the child attends; family gets 'seat opened' copy instead of 'resumed'. | Inject ResumeEnrollment (resume=) into the parent-composition promote, matching composition/admin.py:817. | backend/v2/composition/parent.py:947-955 (verified: no resume=); promote_from_waitlist.py:141-183 (verified); event_handlers.py:265 |
| high | Enrollment | terminal (any) while student is HELD in the same session | enrollments — second active row for the same student+session | Registration approve treats a held row as no conflict: find_for_session_student returns active/no-status/paused only, and the explicit check is {'active','paused'}; SeatBroker may reclaim the same student's hold to seat the new row. | Conflict set = LIVE ({active,paused,held}) plus reclaim_pending in find_for_session_student and admin_registration_review._assert checks. | backend/v2/contexts/enrollment/infrastructure/mongo_enrollment_writer.py:436-442 (verified); backend/v2/composition/admin_registration_review.py:302-306 (verified) |
| high | Enrollment | parent self-cancel (immediate or scheduled) / admin DELETE | Left tab / GetLeavingReport | Self-cancel writes legacy status 'cancelled' and event_type 'cancelled'; admin DELETE route writes 'removed'; DEPARTURE_EVENT_TYPES contains 'deleted' but neither 'cancelled' nor 'removed', so these departures never appear in the Left tab. | Add 'cancelled'/'removed' to DEPARTURE_EVENT_TYPES (or migrate writers to canonical spellings) — #744. | backend/v2/contexts/enrollment/application/use_cases/leaving_report.py:29-38 (verified); mongo_enrollment_writer.py:217,296; self_cancel.py:722; sessions_routes.py:585-605 |
| high | Enrollment | dropped / withdrawn / held (student leaves or is held) | makeup_requests (pending/approved) + occurrence_roster_entries on OTHER sessions | _drop_future_occurrence_roster is scoped to the cancelled enrollment's session_id; a make-up targets a different session by construction, so the seat survives and the coach sheet still shows the MAKE-UP row; HoldEnrollment has no roster cleanup at all; pending make-ups sit until the 5-min expiry job. | On terminal/hold transitions purge the student's future roster rows across all sessions and decline pending make-ups when no LIVE enrollment remains. | admin_writes.py:298-326 (verified: single session_id); coaching_lookups.py:101-113; holds.py:125-290 (no OccurrenceRosterCleanup) |
| high | Enrollment | dropped (last live enrollment for the family) | account_credit_ledger APPROVED credits; parent_digest_sends; parent_billing_customers saved card; autopay_consents | Credits stay attached to parent_id and silently expire at 365d (no cash-out, no reminder); parent daily digest keeps sending because _list_children uses students.list_for_parent with no enrollment filter; saved card and consent persist with no lifecycle end. | Left-tab read model must join credit balance, card-on-file and digest state; digest audience must derive from LIVE enrollments; a 'refund unused credit' owner action on Left. | backend/v2/composition/digests.py:661-665 (verified); mongo_credit_ledger_repo.py:44-410 (verified: no void/unapply/refund method); withdrawal_credit.py:242 |
| high | Session | cancelled (DELETE /admin/sessions/{id}) | waitlist_entries (waiting), trial_requests (pending/approved for the session), makeup/trial roster seats held by students from OTHER sessions | CancelSession has zero waitlist/trial references (verified). Waiting rows stay 'waiting' on a dead session (invisible: GET /admin/waitlist walks upcoming only); pending trials stay in the queue; other-session make-up seats are not purged and families not told. Only the outbox promotion is defensively skipped. | Cascade: mark waiting rows removed(reason session_cancelled) + email; deny/reopen trials; purge all roster rows for the session's future occurrences and reopen make-ups (as CancelSessionOccurrence already does per date). | admin_writes.py:591-757 (verified keyword scan); promote_from_waitlist.py:127-136 (verified); cancel_session_occurrence.py:164-173,221-281 |
| high | SessionOccurrence | hard-deleted by maintain_session_occurrences after a schedule/weekday edit | absence_notices.occurrence_id, makeup_requests.missed/target/approved_target_occurrence_id, trial_requests.assigned_occurrence_id, occurrence_roster_entries, session_feedback.occurrence_id | _is_clean_future_occurrence checks only attendance, coach_attendance and payout_period_lines, then delete_one. All five dependents dangle; a window-met absence notice can no longer unlock a make-up; approved seats vanish; nobody notified. | Either soft-cancel (reuse CancelSessionOccurrence: purge roster, reopen make-ups/trials, notify) or extend the cleanliness check to the five collections and re-key them to the new occurrence_id. | backend/v2/composition/admin.py:2447-2470 (verified), :2521-2523 |
| high | Application | WAITLISTED | Payment (first-month proration), Enrollment (on later promotion), application.enrollment_id | waitlist() has no refund and no skip_period call (verified grep empty); PromoteFromWaitlist mints a bare Enrollment with no skip_periods/enrolled_at so the family is invoiced again for month one; application stays WAITLISTED forever (no application repo in PromoteFromWaitlist); registrations detail prints raw 'WAITLISTED'. | On waitlist: refund or convert proration to a credit (or stamp skip period on eventual enrollment); on promotion: link application.enrollment_id and set APPROVED. | backend/v2/composition/admin_registration_review.py:505-578 (verified); promote_from_waitlist.py:185-192 |
| high | Application | CAPACITY_FAILED_REFUND_FAILED / CHECKOUT_EXPIRED / REFUNDED / DECLINED | parent (money retained or dead-end), owner attention | log.exception only on refund failure, no retry, no attention item; CHECKOUT_EXPIRED/REFUNDED have no outbound edge and are not in _CHECKOUT_STARTABLE_STATUSES so the parent retypes a whole application; no admin list shows decided/expired applications. | Owner attention item + refund retry; reopen edge to DRAFT for expired/refunded; decided-applications list. | backend/v2/composition/event_handlers.py:233-240; composition/parent.py:494; manage_application.py:304-323; registration_routes.py:35-44 |
| high | TrialRequest | approved, date passes, not converted | lifecycle state trial_done / lost; prospective child | 'completed' is declared but never written; approved rows never expire; prospective child never becomes a Student; parent never told approve/deny date; LinkTrialConversion matches by parent not child (sibling converts wrong trial). | Derive trial_done from assigned occurrence end_at < now; write completed from attendance or a daily sweep; match conversion by child name+DOB; send approve/deny emails. | backend/v2/contexts/enrollment/domain/self_service.py:242; trial_requests.py:240-306,366-393; mongo_trial_request_repo.py:88-99 |
| high | Invoice | void (admin or enrollment-stop) | account_credit_ledger entries already applied to that invoice; credit_applications | No reverse/unapply method exists on the credit repo (verified method list); void guard checks balance==total only, so a monthly invoice that consumed credit voids with the credit still decremented. | Restore applied credit (remaining += applied, remove applied_invoice_ids) on void; or refuse void when applied credit exists. | backend/v2/contexts/billing/infrastructure/mongo_credit_ledger_repo.py:44-410 (verified); composition/lifecycle_billing.py:276-298 (verified) |
| high | LedgerPayment | refunded via ACH return (invoice reopened) | dunning_states for the reopened invoice | Ladder was set 'resolved' on the earlier success; prepare_due_states skips any invoice that already has a row of ANY status; the reopened balance is never retried or reminded. | ACH-return handler must re-arm (or delete+recreate) the ladder; prepare must re-arm resolved/suppressed rows whose invoice became chargeable again. | backend/v2/contexts/billing/infrastructure/mongo_dunning_state_repo.py:175-190 (verified), :303-306 (verified); handle_webhook_event.py:2062-2110 |
| high | DunningState | suppressed (autopay_not_active) / dunned | receivable collection; owner notification; autopay re-enable | Suppressed rows never reopen even after autopay re-enable; dunned sends parent terminal notice but owner gets only the ops-digest count; admin enable route accepts only paused rows so staff cannot re-enable after a dunning disable. | Owner inbox item on dunned/failed; re-arm ladder on autopay re-activation; admin enable for disabled rows with a saved card. | mongo_dunning_state_repo.py:284-302 (verified); process_dunning_retries.py:282-284,385-430; autopay_status.py:34-41 |
| high | Invoice | created without enrollment_id (manual draft / Mode B line) | dunning ladder, lifecycle voiding, overdue reminders | Excluded from prepare_due_states (candidates require enrollment_id) and from ApplyEnrollmentLifecycle; never auto-chased. | Overdue reminder job (step 3) must key on parent_id + due_date, not enrollment_id. | mongo_dunning_state_repo.py:186-189 (verified: `and str(doc.get('enrollment_id') or '')`); admin.py:1622-1655; add_invoice_line.py:160-200 |
| high | User (parent) | status set inactive/disabled via PATCH /admin/users/{id} | academy_memberships, Firebase account, AuthClaims, invoices/autopay/dunning keyed by parent_id, students.parent_id | 'Disable' does not disable: _to_domain never maps global_status so LoadAuthClaims._user_is_active defaults to active; membership stays active; Firebase never disabled; billing keeps invoicing/charging; students stay attached (no linked_student_count guard). | Map users.status → global_status / is_active in _to_domain; set membership status on disable; refuse disabling a parent with live children (or force re-parent); Firebase disable. | backend/v2/contexts/identity/infrastructure/mongo_user_repo.py:96-112 (verified: no global_status), :868-870; load_auth_claims.py:128-136 (verified); directory_routes.py:232-262 |
| high | User (coach) | coach role removed / user disabled | sessions.coach_id, sessions.assistant_coach_ids, session_occurrences.scheduled/actual/substitute_coach_id, payout_periods, coach_rates | No handling: ids dangle; coach_name renders None; ListMonthlyPayroll drops the coach for months without occurrences even if an unpaid period exists; only a display session_count on the user card. | 'Reassign before removing' guard listing future sessions; departed-coach-with-unpaid-period surface. | mongo_user_repo.py:717-726,1324-1358; manage_user_roles.py (no session reference); list_monthly_payroll.py:45-59 |
| high | Student | parent changed (change_admin_student_parent) | invoices, account_credit_ledger, waiver_signatures, waitlist_entries, autopay consent | By design left on the old parent (warning string only); impact_counts counts legacy waiver_acceptances not waiver_signatures; new parent's family view lacks the child's prior invoices/credits; a waiver signed by the old adult still counts as valid. | Rehome open invoices/credits/waitlist to the new parent (or create an owner task); mark prior waiver signature outdated for the new parent. | backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py:578-641, :1496-1518 |
| high | Student | students.status hand-set to paused/inactive/cancelled | waiver compliance list, directory filter, parent card chip | Waiver compliance excludes every non-active students.status even with live enrollments; enrollments keep billing; re-enrolment never resets the stale status. | Retire students.status (audit item 1) and drive waiver compliance from LIVE enrollments. | backend/v2/contexts/onboarding/infrastructure/mongo_admin_waiver_repo.py:152-162 (verified); mongo_student_writer.py:39-46,72-81 |
| high | LevelUpRecommendation | APPROVED | next RecommendLevelUp for the same program; GetProgressSummary next_action | COMPLETED is never written; repo treats APPROVED as active, so a student can be levelled up exactly once per program and the summary reports 'awaiting_admin_approval' forever. | Transition to COMPLETED at end of _apply_approval or exclude APPROVED from the active predicate. | backend/v2/contexts/student_progress/infrastructure/mongo_recommendation_repo.py:81-105 (verified); recommend_level_up.py:95-104 |
| high | PayoutPeriod | approved / paid | coach_attendance marks, occurrence cancellations, audit trail | MarkCoachAttendance has no payout reference (verified grep empty) so inputs drift after payment; approve/mark-paid write no audit entry; reopen of paid clears paid_* with no clawback. | Lock inputs (or flag stale) once approved/paid; write generated/approved/marked_paid audit entries; paid → only 'corrected' successor. | mark_coach_attendance.py:47-80 (verified); approve_payout_period.py:35-99; payout_period.py:187-202 |
| high | WaiverTemplate | published (prior template superseded) | assigned_to_registration flag, waiver_signatures (derived outdated), family communication | Flag does not move forward; registration read still honours the superseded template ($in active/published) while the parent prompt reads active only → readers disagree; every family becomes 'outdated' silently with no remind action. | Carry assigned_to_registration to the new version on publish; single derived waiver status; re-sign reminder. | mongo_waiver_template_repo.py:134,174; mongo_parent_waiver_repo.py:62-74; mongo_registration_waiver_repo.py:53-73 |
| high | Enrollment | paused / held (LIVE but not active) | session announcements inbox visibility + urgent email audience | Both filter enrollments.status=='active', so paused/held families see and receive nothing for their class. | Filter on LIVE statuses. | backend/v2/composition/parent.py:2579-2586 (verified); mongo_audience_resolver.py:87-92 (verified) |
| high | User (parent) email | hard bounce / complaint → email_suppressions active | invoices (delivery_failed), digests (failed retryable=false), announcements, owner visibility | Only the platform operator can list/release; academy admin has no chip/list; suppressed digest failures are excluded from ops count; email edit silently detaches the suppression. | Admin-scoped suppression surface (audit item 6) plus link suppression to user_id on email change. | platform/suppression_routes.py:67-102; gated_send_port.py:40-75; mongo_suppression_repo.py:74-76; ops_digest.py:305-322 |
| medium | Enrollment | dropped (already terminal) → CancelEnrollment again | enrollments.status, enrollment_events, billing_sync | Guard is only canonical_status=='deleted', so a dropped row is overwritten to 'deleted', a second departure event is written and billing_sync runs twice; leaving report double-counts. | Refuse any TERMINAL pre-image (DROPPED_SPELLINGS \| DELETED_SPELLINGS). | admin_writes.py:1245-1250 (verified); domain/models.py:152-159 |
| medium | Enrollment | pause approved (indefinite) | scheduled_enrollment_actions | Only fixed pauses schedule resume_from_pause; indefinite pauses store review_on but nothing is scheduled or reminded; run_at for fixed pauses is 00:00 UTC not academy midnight. | Schedule a review/reminder action at review_on; build run_at in academy tz. | backend/v2/contexts/enrollment/application/use_cases/pause_requests.py:357-380; main.py:228-300 (verified: no review job) |
| medium | Session | cancelled | session_occurrences with a coach override (actual/substitute) or attendance | maintain_session_occurrences soft-cancels only 'clean' rows and does not flip is_billable/is_payable; a future occurrence with a replacement coach stays 'scheduled', derives to 'completed' after end_at and is payable for a class that never ran. | Cascade cancel must mark every future occurrence cancelled with is_payable=false regardless of override. | backend/v2/composition/admin.py:2447-2470 (verified), :2503-2519; shared/occurrences.py:25-37 |
| medium | SessionOccurrence | cancelled (single date) after payroll snapshot | payout_period_lines (draft) / approved-paid periods | cancel_scheduled flips is_payable=false but never removes draft lines and never checks approved/paid periods; a paid period keeps paying for the cancelled class until manually reopened + recomputed. | Cancel must reject or flag occurrences on approved/paid periods and clear draft lines (mirror _clear_or_reject_replacement_payout_snapshots). | mongo_occurrence_repo.py:250-282; admin.py:2848-2862 (verified — replacement path only) |
| medium | Application | DRAFT past expires_at (never transitions) | enrollment_funnel lead counts, People directory lead states | ABANDONED is declared but has no writer; expires_at is dead; stale DRAFT/CHECKOUT_PENDING rows count as leads forever. | Daily job: DRAFT/CHECKOUT_PENDING older than expires_at → ABANDONED; derived 'abandoned' state in the lifecycle spec. | manage_application.py:312,407; onboarding/domain/models.py:105; finance/application/use_cases/enrollment_funnel.py:38,48 |
| medium | Invoice | void (stripe_invoice_id-linked) | Stripe invoice object | build_void_billing_invoice touches ledger + dunning only; Stripe invoice stays open in Stripe. | Call stripe void/mark_uncollectible when stripe_invoice_id is set. | composition/lifecycle_billing.py:276-298 (verified: no Stripe call); stripe_gateway.py:537 |
| medium | Enrollment | hold reclaimed/expired or coach roster delete (no EnrollmentCancelled) | level_up_recommendations (RECOMMENDED), student_level_progress | ExpireLevelUpRecommendations runs only from the outbox handler; hold-driven drops emit nothing so the rec lingers with a Withdrawn chip; student_level_progress 'withdrawn' is never written. | Emit EnrollmentCancelled from finalize_reclaim; write level progress withdrawn on last-enrollment-terminal. | event_handlers.py:242-266 (verified); seat_broker.py:192-290 (verified no outbox); student_progress/domain/models.py:29 |
| medium | PayoutPeriod | draft hard-deleted by replacement-coach change | payout_audit_log rows for that period_id | delete_many on lines + periods; audit log has no delete method and rows orphan; no audit entry for the deletion itself. | Recompute instead of delete, or delete/mark audit rows and write a 'deleted' audit entry. | backend/v2/composition/admin.py:2848-2862 (verified); mongo_payout_audit_log.py:34-43 |
| low | Session | cancelled | staff roster alerts | One 'class cancelled: <student>' staff email PER ENROLLED STUDENT; no single session-level notice; none at all if zero live enrollments. | One session-level cancellation notice to coach/assistants/admins plus per-family parent notices. | admin_writes.py:710-716; roster_notifications.py:404-470 |
| low | WaitlistEntry | skipped / removed | enrollment_events, family communication | Silent: no event row, no email; only Skip/Remove buttons on the session page. | Record 'waitlist_skipped'/'waitlist_removed' events and notify the family. | admin_writes.py:2314-2327; waitlist_routes.py:103-118 |
| low | Academy (tenant) | suspended / cancelled | academy_memberships | Handled elsewhere: middleware returns 423 for every non-platform request; memberships untouched and re-serve on reactivate. | None. | backend/v2/shared/auth/middleware.py:167-182; platform/application/use_cases/tenant_lifecycle.py:200-260 |
| low | Enrollment | any terminal | attendance, enrollment_events, enrollment_hold_notice_sends, absence_notices | Retained as history; never deleted (correct). | None beyond the per-student timeline index (audit item 6). | mongo_attendance_repo.py:37-97; mongo_enrollment_event_repo.py:40-65 |

## 2. Gaps not covered by the plan (32)

### PauseEnrollment has no LIVE guard; pause_requests approve/decline unguarded
**Impact:** high · **Attach to:** step 2

**Problem.** A dropped/deleted row can be paused by the admin pause route or by approving a stale pause request: it releases a seat it does not hold, adds a waitlist entry and writes deferrals for a departed student. Repo approve/decline do not CAS on 'pending', so approved→declined (enrollment stays paused with live deferrals + scheduled resume) and declined→approved are both reachable.

**Fix.** PauseEnrollment: raise unless e.status in LIVE. mongo_pause_request_repo.approve/decline: update_one filter {status:'pending'} and raise on no match. On every terminal enrollment transition decline pending pause_requests with reason enrollment_ended.

**Evidence.**
- `backend/v2/contexts/enrollment/application/use_cases/admin_writes.py:1686-1706 (verified)`
- `backend/v2/contexts/enrollment/infrastructure/mongo_pause_request_repo.py:97-128 (verified)`
- `backend/v2/contexts/enrollment/application/use_cases/pause_requests.py:254-256`

### Departed families auto-promoted from their own paused reclaim row
**Impact:** high · **Attach to:** step 4

**Problem.** PauseEnrollment adds a 'waiting' entry for the paused student; only ResumeEnrollment removes it. Withdraw / CancelEnrollment / StopAll / scheduled cancel of a paused row leave it, so the next freed seat mints a fresh active Enrollment for a family that left and emails 'seat opened'. Re-enroll from the Left tab would then find two rows.

**Fix.** Inject the waitlist repo into WithdrawEnrollment/CancelEnrollment/scheduled cancel and call remove_waiting_for_session_student when the pre-image is paused; CancelSession should mark all waiting rows removed.

**Evidence.**
- `admin_writes.py:1712-1735, :1928-1953, :2172-2173 (verified)`
- `promote_from_waitlist.py:141-192 (verified)`

### Outbox waitlist promotion of a paused student skips billing resume
**Impact:** high · **Attach to:** step new

**Problem.** The parent composition builds PromoteFromWaitlist without resume= or seat_broker; a paused head-of-queue student becomes active via bare update_status with no billing_sync 'resumed', autopay stays paused, the pause deferral stays active and monthly invoices keep being skipped while the child attends. Silent revenue loss.

**Fix.** Pass resume=ResumeEnrollment(...) and seat_broker into the parent-composition PromoteFromWaitlist exactly as composition/admin.py:817 does; add a test for paused-head promotion via the outbox path.

**Evidence.**
- `backend/v2/composition/parent.py:947-955 (verified)`
- `backend/v2/contexts/enrollment/application/use_cases/promote_from_waitlist.py:141-183 (verified)`
- `backend/v2/composition/event_handlers.py:265`

### finalize_reclaim is a half-drop
**Impact:** high · **Attach to:** step new

**Problem.** Hold reclaimed/expired/orphaned drops do billing_sync + event + family email only: no scheduled-action retirement, no deferral close, no occurrence-roster cleanup, no EnrollmentCancelled (level-up expiry and waitlist promotion never run), no staff roster alert, no pause-request cleanup, no credit decision. The Left tab will show these as left while dependents behave as if live.

**Fix.** Extract the post-terminal bundle from WithdrawEnrollment into one helper and call it from seat_broker.finalize_reclaim (and from the scheduled cancel path).

**Evidence.**
- `backend/v2/contexts/enrollment/application/seat_broker.py:192-290 (verified)`
- `admin_writes.py:1999-2060`

### Registration approval mints a second enrollment for a HELD student
**Impact:** high · **Attach to:** step new

**Problem.** find_for_session_student returns only active/no-status/paused rows and the explicit conflict set is {'active','paused'}, so approving a new application for a student on hold in the same session creates a second active row; SeatBroker may reclaim that very hold to seat it, dropping the child from their own seat.

**Fix.** Use LIVE ∪ {'reclaim_pending'} as the conflict set in find_for_session_student, has_active_enrollment and admin_registration_review; treat a held existing row as 'return from hold' instead.

**Evidence.**
- `mongo_enrollment_writer.py:436-442 (verified)`
- `admin_registration_review.py:302-306 (verified)`
- `mongo_student_repo.py:215`

### WAITLISTED registration double-bills month one and never links to the promoted enrollment
**Impact:** high · **Attach to:** step 3

**Problem.** waitlist() retains the captured first-month proration with no refund/credit/skip_period; PromoteFromWaitlist mints a bare Enrollment with no skip_periods so the monthly generator invoices month one again; the application stays WAITLISTED forever and _assert_reviewable refuses approve. Audit item 3 only adds a 'waitlisted' email.

**Fix.** On waitlist: convert proration to an APPROVED credit or stamp a pending skip period; PromoteFromWaitlist takes the application repo, sets APPROVED + enrollment_id and carries the skip period.

**Evidence.**
- `backend/v2/composition/admin_registration_review.py:505-578 (verified: no refund/skip/notify calls)`
- `promote_from_waitlist.py:185-192`
- `admin_registration_review.py:642-648`

### Silent application terminals and the ABANDONED state nobody writes
**Impact:** high · **Attach to:** step 5

**Problem.** CAPACITY_FAILED_REFUND_FAILED retains the parent's money with log.exception only; CHECKOUT_EXPIRED/REFUNDED are dead-ends (not checkout-startable) forcing a retyped application; ABANDONED has no writer and expires_at is never read, so stale drafts count as leads forever; no admin list of decided/expired applications.

**Fix.** Owner attention item + refund retry for REFUND_FAILED; reopen edge CHECKOUT_EXPIRED/REFUNDED→DRAFT; daily sweep DRAFT/CHECKOUT_PENDING past expires_at→ABANDONED; GET /admin/registrations?status=decided.

**Evidence.**
- `backend/v2/composition/event_handlers.py:233-240`
- `backend/v2/composition/parent.py:494`
- `manage_application.py:304-323,407; onboarding/domain/models.py:105`
- `enrollment_funnel.py:38,48`

### Trial lifecycle cannot reach trial_done and has zero communications
**Impact:** high · **Attach to:** step 2

**Problem.** 'completed' is declared but never written; approved trials never expire after their date; prospective children never become a Student; parent is not told approve/deny/date; LinkTrialConversion matches by parent (sibling converts the wrong trial); pending trials for a cancelled session stay queued.

**Fix.** Derive trial_done from assigned occurrence end_at < now in the lifecycle spec; daily sweep approved+past→completed; approve/deny emails via the absence-notification adapter pattern; match conversion by child name+DOB.

**Evidence.**
- `backend/v2/contexts/enrollment/domain/self_service.py:242`
- `trial_requests.py:240-306, :366-393`
- `mongo_trial_request_repo.py:88-99`

### Session cancel does not cascade to waitlist, trials or other-session make-up seats
**Impact:** high · **Attach to:** step 6

**Problem.** CancelSession touches enrollments/occurrences only: waiting rows stay 'waiting' (invisible because the waitlist page walks upcoming sessions), pending trials stay queued, make-up/trial seats held by students from other sessions on this session's future dates are not purged and nobody is emailed. CancelSessionOccurrence already does all three per date.

**Fix.** CancelSession calls remove-all-waiting(session_id, reason session_cancelled) + email, denies/reopens trials, and purges all future roster rows for the session (not per enrolled student).

**Evidence.**
- `admin_writes.py:591-757 (verified: no waitlist/trial references)`
- `cancel_session_occurrence.py:164-173,221-281`
- `waitlist_routes.py:25-30`

### Schedule edit hard-deletes occurrences and orphans notices, make-ups, trials, seats
**Impact:** high · **Attach to:** step new

**Problem.** maintain_session_occurrences deletes any 'clean' future occurrence; cleanliness ignores absence_notices, makeup_requests, trial_requests, occurrence_roster_entries and session_feedback. A weekday change re-mints every occurrence_id and loses every approved seat and absence notice without notification. Audit item 3's 'Schedule changed' email does not fix the data.

**Fix.** Replace delete_one with a soft cancel that runs the CancelSessionOccurrence cleanup (purge roster, reopen make-ups/trials, notify), or extend _is_clean_future_occurrence to the five collections and re-key.

**Evidence.**
- `backend/v2/composition/admin.py:2447-2470 (verified), :2521-2523`

### Approved make-up seats on other sessions survive withdraw/stop-all/hold; 'completed' never written
**Impact:** high · **Attach to:** step 6

**Problem.** _drop_future_occurrence_roster is scoped to the cancelled enrollment's session; make-ups target a different session, so the coach sheet keeps a MAKE-UP row that is rejected at tap time; HoldEnrollment has no roster cleanup; attendance on a makeup row never closes the request so every used make-up stays 'approved'.

**Fix.** On terminal/hold: remove_future_for_student across all sessions and decline pending make-ups when no LIVE enrollment remains; MarkAttendance with entry_source='makeup' transitions the request to completed.

**Evidence.**
- `admin_writes.py:298-326 (verified)`
- `coaching_lookups.py:101-113`
- `holds.py:125-290`
- `self_service.py:215; mark_attendance.py:181-194`

### Void does not restore applied credit or void the Stripe invoice
**Impact:** high · **Attach to:** step new

**Problem.** Credit repo has no reverse/unapply method; void guard checks balance==total only, so a monthly invoice that consumed credit voids with the credit still decremented and applied_invoice_ids pointing at a void invoice. stripe_invoice_id-linked invoices stay open in Stripe.

**Fix.** Add unapply_credits(invoice_id) called from build_void_billing_invoice and ApplyEnrollmentLifecycle; call stripe void/mark_uncollectible when stripe_invoice_id is set; write a billing_audit row for void.

**Evidence.**
- `mongo_credit_ledger_repo.py:44-410 (verified method list)`
- `composition/lifecycle_billing.py:276-298 (verified)`
- `apply_enrollment_lifecycle.py:148-166`

### Dunning ladders are one-way: ACH return, autopay re-enable and dunned never re-arm
**Impact:** high · **Attach to:** step 3

**Problem.** prepare_due_states skips any invoice with an existing row of any status; ACH return reopens the invoice but the ladder stays resolved; suppressed(autopay_not_active) never reopens after enable; admin enable accepts only paused rows so staff cannot switch autopay back on after a dunning disable; parked non-retryable rows sit active forever; schedule is a compile-time constant. Step 3's reminder job covers non-autopay reminders but not ladder re-arming.

**Fix.** Re-arm on ACH return and on autopay activation (delete+recreate or reopen); allow admin enable for disabled rows with has_saved_card; make DUNNING_SCHEDULE_DAYS academy-configurable alongside the reminder offsets.

**Evidence.**
- `mongo_dunning_state_repo.py:175-190 (verified), :284-306 (verified)`
- `handle_webhook_event.py:2062-2110`
- `autopay_status.py:34-41; process_dunning_retries.py:385-430`
- `domain/dunning.py:10`

### Invoices without enrollment_id are never chased
**Impact:** high · **Attach to:** step 3

**Problem.** Manual drafts and Mode-B on-the-fly invoices carry no enrollment_id; prepare_due_states requires it and lifecycle voiding ignores them; the planned reminder job must not repeat the same filter.

**Fix.** Key the due+15/+20 reminder job on (parent_id, due_date, balance>0) over all invoices regardless of enrollment_id.

**Evidence.**
- `mongo_dunning_state_repo.py:186-189 (verified)`
- `composition/admin.py:1622-1655; add_invoice_line.py:160-200`

### Level-up APPROVED is permanent: one level-up per program per student
**Impact:** high · **Attach to:** step new

**Problem.** COMPLETED is never written and the repo treats APPROVED as active, so RecommendLevelUp raises ActiveRecommendationExists for every later level; GetProgressSummary reports awaiting_admin_approval forever; hold-driven drops never expire RECOMMENDED rows; none of the eight StudentProgress events has a subscriber; certificates can persist with blank names.

**Fix.** Set COMPLETED at end of _apply_approval (and exclude APPROVED from the active predicate); emit EnrollmentCancelled from finalize_reclaim; add one handler for LevelUpRecommended/StudentLeveledUp/CertificateIssued in step 7; fail approval when certificate display lookup misses.

**Evidence.**
- `mongo_recommendation_repo.py:81-105 (verified)`
- `recommend_level_up.py:95-104`
- `get_progress_summary.py:209-214,256-271`
- `progress_routes.py:471-509`

### User 'Disable' does not disable; no offboarding transition exists
**Impact:** high · **Attach to:** step new

**Problem.** _to_domain never maps users.status → global_status, so LoadAuthClaims treats every user as active; membership stays active; Firebase is never disabled; membership statuses invited/suspended/removed have no writer; CannotRemoveLastRole blocks the only other path. A disabled parent still signs in and is still billed; a disabled coach still appears on sessions.

**Fix.** Map status in _to_domain (is_active + global_status); disable sets membership status='suspended' and calls Firebase disable; refuse disabling a parent with live children / a coach with future sessions unless reassigned.

**Evidence.**
- `mongo_user_repo.py:96-112 (verified), :868-870`
- `load_auth_claims.py:128-136 (verified)`
- `identity/domain/models.py:59-60; firebase_admin_adapter.py:218-386 (no disable_user)`

### Coach role removal leaves sessions/occurrences/payroll pointing at the ex-coach
**Impact:** high · **Attach to:** step new

**Problem.** ManageUserRoles has no session handling; sessions.coach_id, assistant_coach_ids and occurrence coach ids dangle; coach_name renders None; ListMonthlyPayroll hides an unpaid period for a coach with no occurrences that month; EditSession.assistant_coach_ids bypasses eligibility checks so a parent id can be stamped as assistant.

**Fix.** Guard role removal with a 'future sessions assigned' check + reassign dialog; departed-coach-with-unpaid-period row in payroll; run the SetSessionAssistants eligibility check inside EditSession.

**Evidence.**
- `mongo_user_repo.py:717-726,1324-1358`
- `list_monthly_payroll.py:45-59`
- `admin_writes.py:515-517 vs admin_session_staff.py:133-151`

### Payroll inputs drift after approve/paid; money-moving transitions are unaudited; paid is reopenable
**Impact:** high · **Attach to:** step new

**Problem.** MarkCoachAttendance and CancelSessionOccurrence never check approved/paid periods (only the replacement-coach path does); generated/approved/marked_paid audit actions are declared but never written; reopen of a paid period clears paid_* with no clawback; draft periods are hard-deleted on replacement change leaving payout_audit_log orphans; coach-attendance PATCH is admin-gated while every payout mutation is owner-gated.

**Fix.** Lock or flag inputs once approved/paid; write the three audit entries; paid → 'corrected' successor only; recompute instead of delete drafts; align the coach-attendance route to require_owner or flag stale periods.

**Evidence.**
- `mark_coach_attendance.py:47-80 (verified: no payout reference)`
- `composition/admin.py:2848-2862 (verified)`
- `approve_payout_period.py:35-99; payout_period.py:187-202; payout_audit.py:18-26`
- `sessions_routes.py:413-417 vs payout_period_routes.py:299-405`

### Change-parent strands money and history on the old parent
**Impact:** high · **Attach to:** step new

**Problem.** invoices, credits, waiver_acceptances, waitlist rows stay under the previous parent by design (warning string only); the new family view lacks the child's invoices/credits; billing keeps owing/crediting a user who no longer has the child; no follow-up task is created.

**Fix.** Rehome open invoices/credits/waitlist rows atomically or create an owner attention item listing what stayed behind.

**Evidence.**
- `mongo_student_repo.py:578-641, :1496-1518`

### students.status writers must go, and waiver compliance must stop reading it
**Impact:** high · **Attach to:** step 2

**Problem.** Audit item 1 deletes UpdateAdminStudentCommand.status but does not mention that mongo_admin_waiver_repo excludes every non-active students.status, so a hand-set 'paused' child with live enrollments silently leaves the unsigned-waiver list today, and re-enrolment never resets the stale string.

**Fix.** In step 2 drop the status filter in _student_docs and join student_ids_with_live_enrollment instead; one-off migration to $unset students.status.

**Evidence.**
- `mongo_admin_waiver_repo.py:152-162 (verified)`
- `mongo_student_writer.py:39-46,72-81`

### Credits have no admin grant/void, no cash-out on leave, silent expiry
**Impact:** medium · **Attach to:** step 4

**Problem.** MANUAL_CREDIT is minted only by overpayment; no route grants/adjusts/voids a credit; unused credit for a departed family lapses at 365 days with no reminder; CLASS_CANCELLATION_CREDIT has no expiry (inconsistent); no communication on credit creation; ACH-return void of spent credit is log.warning only.

**Fix.** Owner actions grant/void/refund-credit; Left tab shows credit balance with 'Refund unused credit'; expiry reminder at -30d; owner attention item on spent-credit void.

**Evidence.**
- `mongo_credit_ledger_repo.py (no grant/void)`
- `withdrawal_credit.py:242; apply_enrollment_move.py:653; apply_occurrence_cancellation.py:427-447`
- `mongo_billing_ledger_repo.py:1305-1313`

### Saved payment method has no end of life
**Impact:** medium · **Attach to:** step 3

**Problem.** No handler for payment_method.detached / card expiry / Stripe-side removal; has_saved_card stays True so admin charge and ladders keep hitting a dead method until 4 declines; parent has no remove/replace-card UI and receives no 'card saved' or 'card expiring' notice; autopay consent is never revoked on pause/disable.

**Fix.** Handle payment_method.detached + card expiry webhooks; parent 'Update card' (audit item 2e) plus remove; revoke consent row on disable.

**Evidence.**
- `mongo_parent_billing_customer_repo.py:44-160 (no removal method), :229-236`
- `handle_webhook_event.py:537,684-690`
- `pause_family_autopay.py:120-140`

### Parent daily digest keeps sending to fully-withdrawn families
**Impact:** medium · **Attach to:** step 4

**Problem.** _list_children uses students.list_for_parent with no enrollment filter; has_children is bool(children); a family whose every child left keeps claiming a digest row daily until unsubscribe/bounce. Parent digest failures have no admin read surface.

**Fix.** Derive digest audience from the step-2 lifecycle (any LIVE child); add parent_digest_sends to the delivery log.

**Evidence.**
- `backend/v2/composition/digests.py:661-665 (verified), :475-476`
- `parent_digest_view.py:92-93`

### Waiver publish breaks the registration link and re-parenting inherits a stranger's signature
**Impact:** medium · **Attach to:** step new

**Problem.** assigned_to_registration does not move to the new version; the registration read ($in active/published) and the parent prompt (active only) disagree until re-assigned; publish sends nothing and there is no remind action; retired/expires_at/is_deleted are dead states; share links are minted 'active' with no resolver; student.parent_changed leaves signatures under the old parent and impact_counts ignores waiver_signatures.

**Fix.** Carry the flag forward on publish; single derived waiver status in the lifecycle spec; re-sign reminder; delete dead states or add writers; on parent change mark signature outdated_for_parent.

**Evidence.**
- `mongo_waiver_template_repo.py:134,174; mongo_registration_waiver_repo.py:53-73; mongo_parent_waiver_repo.py:62-74`
- `mongo_student_repo.py:595-625,1515`
- `mongo_parent_waiver_repo.py:272-300; waiver_routes.py:159`

### Hold start/return send two family emails, one factually wrong
**Impact:** medium · **Attach to:** step 1

**Problem.** HoldEnrollment fires roster_changed('paused') so the parent receives 'Enrollment paused … seat is released' PLUS hold_started; ReturnFromHold sends 'resumed' + enrollment_returned. Same class as the #767 double drop email; 'held'/'returned' are not RosterChangeKind members.

**Fix.** Add held/returned to RosterChangeKind with staff-only routing and make hold_started/enrollment_returned the single family notice.

**Evidence.**
- `holds.py:248-257, :366-390`
- `roster_notifications.py:301-304; ports.py:514-531`

### Scheduled self-cancel disables autopay weeks early and never confirms to the parent
**Impact:** medium · **Attach to:** step 7

**Problem.** billing_sync 'cancelled' fires at request time: autopay disabled and next-month invoices voided while the child still attends the paid month; the 'cancellation_scheduled' alert is staff-only; no 'last class is <date>' reminder (audit lists that as phase-2 comms but not the billing timing).

**Fix.** Defer billing_sync to the scheduled action's execution (keep future-invoice void at request time only if the period is after pending_cancellation_at); parent confirmation at request time.

**Evidence.**
- `self_cancel.py:578-590, :668-676`
- `process_scheduled_cancellation_actions.py:224-231`

### Attendance has no event feed; at_risk and timeline must poll
**Impact:** medium · **Attach to:** step 2

**Problem.** Coaching.AttendanceMarked/Corrected are appended to the outbox but no handler is registered and the dispatcher drops unhandled events; no 'unmarked' occurrence state exists; corrections after payroll are unguarded.

**Fix.** Derive at_risk in the step-2 read model from attendance + past scheduled occurrences (poll); register a no-op-safe handler only if step 5 needs counts; guard CorrectAttendance against approved/paid periods.

**Evidence.**
- `mark_attendance.py:195-210; correct_attendance.py:143-160`
- `shared/events/dispatcher.py:184-187`
- `admin.py:2790-2792`

### Registration-approved enrollments have no 'created' event; no per-student event read
**Impact:** medium · **Attach to:** step 2

**Problem.** approve() records no lifecycle event, so a student whose first enrollment came via registration has no timeline start; the event repo offers list_for_enrollment and a date-range scan only (no student index).

**Fix.** Record 'created' in approve(); add list_for_student + (academy_id, student_id, occurred_at) index in the same PR as the step-2 derivation (audit item 6 depends on it).

**Evidence.**
- `admin_registration_review.py:295-360`
- `mongo_enrollment_event_repo.py:49-65`

### Session edit can lower capacity below reserved_seats; reserved_seats never reconciled
**Impact:** medium · **Attach to:** step new

**Problem.** EditSession has no capacity >= reserved_seats guard; a comment admits drift; PauseEnrollment on a terminal row releases a seat it never held (under-count).

**Fix.** Guard in EditSession; nightly reconcile reserved_seats = count(status in SEAT_HOLDING).

**Evidence.**
- `admin_writes.py:473-583, :949`
- `mongo_session_writer.py:101-110`

### Hold-notice / absence-notice send failures are never retried
**Impact:** medium · **Attach to:** step 7

**Problem.** enrollment_hold_notice_sends and absence_notice_sends write retryable=True on transient failure but no job re-reads them; a mail outage silently loses the family's only hold-start or reclaim notice.

**Fix.** One retry sweep over both claim tables (reuse the digest reclaim pattern).

**Evidence.**
- `composition/hold_notice_send_repo.py:72-80`
- `composition/absence_notifications.py:151-165`
- `main.py:228-300 (verified: no such job)`

### Governance deletion is request-only with no cascade anywhere
**Impact:** low · **Attach to:** step new

**Problem.** student/tenant data-deletion requests are inserted and listed; no executor; 'deletion_requested' is never stamped; when built, none of attendance/absence/makeup/roster/progress/certificates/waivers/messages/digest/audit rows has a cascade or anonymisation hook.

**Fix.** Keep as TODO (future); document the cascade list from this matrix next to the governance use case.

**Evidence.**
- `platform/governance/application/use_cases.py:244-280`
- `governance/domain/models.py:53,57,164`

### Broadcast DM has no recipient validation, no delete, no parent reply
**Impact:** low · **Attach to:** step 7

**Problem.** POST /admin/messages/dm accepts any recipient_id string; DMs and academy broadcasts cannot be deleted; parents/coaches cannot originate a DM; urgent fan-out counts are never persisted.

**Fix.** Validate recipient membership; persist counts on Message (audit item 9 covers fan-out); add soft-delete for DMs; parent reply is a later slice.

**Evidence.**
- `comms_routes.py:77-89; messages.py:198-209,284,318`
- `session_announcements.py:241-282`

## 3. Covered by the plan

- Step 1 / audit item 3: WithdrawEnrollment sends both the roster 'withdrawn' copy and enrollment_dropped (admin_writes.py:2063-2087) — dedupe.
- Step 2 / audit item 1: students.status has one writer; directory filter + SummaryCards + parent partitionByHold + CoachRosterEntry Literal missing reclaim_pending/hold_return_on; derive lifecycle once before pagination and expose on AdminStudentSummary, parent children, CoachRosterEntry; delete UpdateAdminStudentCommand.status; add at_risk from last_seen_at.
- Step 3 / audit item 2: no past-due reminder job in the 13-job registry; dead Notify toggles; receipts only on dunning retry; no owner alert on dunning failure/exhaustion; parent banner lacks decline date/retry date/Update card; #635 processing state; coach payment chip decided; autopay-enabled confirmation and coach payout email listed last.
- Step 4 / audit item 4 + §3 holding area: Left tab on GetLeavingReport (#698), reason_code enum on Drop/Stop-all, Re-enroll on Past rows, parent 'Enroll in a class' with student_id pre-bound, 'Previously enrolled' flag on registration review, 'Which child?' picker, #744 so Delete rows appear, session_type_id vs session_id mismatch to resolve.
- Step 5 / audit item 5: GET /admin/inbox/counts, counts on tab labels, merged Inbox page, owner daily brief phase 2, #747.
- Step 5 / audit item 8: /admin/students becomes the People directory; delete parents/coaches redirects and users/new; list_parents classifies active/left from T1; duplicate-candidate flag; Families default to ≥1 live child; login state on header.
- Audit item 6 (feeds steps 2 and 7): admin-scoped suppression list + release, 'Email undeliverable' chip, delivery_status='suppressed', Timeline tab on student page from enrollment_events(student_id) with list_for_student + index, remove /admin/audit-logs nav.
- Step 6 / audit item 7: 'n/N marked' + Needs-marks badge on Today, cancelled occurrences struck-through (relax mongo_occurrence_repo.py:71 filter), calendar ?date bug, delete /coach/dashboard, remove Billing button + billing-preview-drawer, hide billing_enrollment_routes from coach.
- Step 7 / audit item 3 phase 2 + item 9 + §4 matrix: declined/waitlisted emails, staff alert on registration submit, 'Schedule changed' on EditSession, coach changed, 'seat opened — confirm by', 'last class is <date>', pause-ending, level-up, first-class; broadcast/DM email fan-out + counts; LIVE statuses in _visible_session_ids (paused/held announcements); recipient names; Requests bottom tab; win-back at 30/60/90 (owner decision overrides the audit's deferral).
- Audit item 10: widen collections parent set to prior-period-open parents; include leftover in Owed tile.
- Audit item 11: next_occurrence_at + last_occurrence_attendance_marked on the sessions list; optional window=past|cancelled (surfaces cancelled sessions).
- Audit item 12: delete PayslipsPanel / /admin/coach-payslip / GET /admin/finance/payouts and _derive_from_completed_occurrences; trim /admin/reports (implicitly retires the never-computed reporting snapshot readers).
- Cross-cutting: owner-only guard drift (Draft Void #726, payout approve visible to admins, credit outcomes #742); #751 register every new job in sentry_cron_jobs.
- §3 duplicate-person risks: exact name+DOB binding, spouse second-email duplicates, prospective trial children as derived trialing/trial_done states (not a Student).
- §3 parent identity rule: users.status stays untouched for a parent with zero live enrollments (returning-customer login).

## 4. Derived person lifecycle: implementation spec for #773

**States:** `lead`, `abandoned`, `awaiting_approval`, `waitlisted`, `declined`, `trialing`, `trial_done`, `active`, `at_risk`, `pending_cancel`, `paused`, `on_hold`, `on_hold_reclaiming`, `left`, `never_enrolled`

**Rules (ordered precedence):**

- R0 Scope and inputs. Derive per student_id within academy_id from: enrollments (status normalised via canonical_status: DROPPED_SPELLINGS {withdrawn,dropped} and DELETED_SPELLINGS {cancelled,deleted} → TERMINAL; LIVE = {active,paused,held}; SEAT_HOLDING = {active,held}; plus transient reclaim_pending — backend/v2/contexts/enrollment/domain/models.py:79,88,152-164), enrollment_events, scheduled_enrollment_actions, pause_requests, waitlist_entries, onboarding_applications, trial_requests, attendance + session_occurrences. Ignore students.status entirely (to be deleted). Compute before any pagination/status filter (mongo_student_repo.py:772-830).
- R1 If any enrollment row has status=='active' (SEAT_HOLDING and seated): (a) if that row (newest active by created_at) has pending_cancellation_at set → pending_cancel, date = pending_cancellation_at (self_cancel.py:472-478; mongo_enrollment_writer.py:228-263); (b) else if the student has zero attendance rows (status in present/late/absent — any mark counts as 'seen'; use present/late for at_risk) across the last 3 session_occurrences of any active session with end_at < now and status != cancelled → at_risk, date = last present/late attendance marked_at (AdminStudentSummary.last_seen_at, mongo_student_repo.py:788-790); (c) else active. Active beats every other row status.
- R2 Else if any row has status=='held' → on_hold, date = hold_return_on (else hold_expires_at); if any row (same student) has status=='reclaim_pending' → on_hold_reclaiming (transient; ProcessStalledReclaims resolves within 15 min, main.py:297; RosterPanel today mislabels it ON HOLD, RosterPanel.tsx:40). Coach views must widen the enrollment_status Literal to include reclaim_pending (coach/views.py:50).
- R3 Else if any row has status=='reclaim_pending' with no held row → on_hold_reclaiming (will become left).
- R4 Else if any row has status=='paused' → paused; date = run_at of the pending scheduled_enrollment_actions row with action=='resume_from_pause' for that enrollment (pause_requests.py:357-380), else the approved pause_request.resume_on, else review_on (indefinite pause: show 'until reviewed').
- R5 Else if rows exist and every row is TERMINAL → left. left_at = occurred_at of the newest enrollment_events row for the student with event_type in DEPARTURE_EVENT_TYPES ∪ {'cancelled','removed','hold_expired'} (leaving_report.py:29-38 must be widened — #744); reason = event.reason_code (new, step 4) else event.reason; fallback when no event: enrollment.cancelled_at (admin_writes.py:1257-1262). Flag returning=false here.
- R6 Else (no enrollment rows) derive a lead state, evaluated in this order, newest row first: (a) waitlist_entries status=='waiting' for student_id → waitlisted (date joined_at; session title); (b) onboarding_applications status in {PENDING_APPROVAL, APPROVING, WAITLISTING, DECLINING, CHECKOUT_PENDING} → awaiting_approval (date created_at/updated_at); (c) application status in {DECLINED, REFUNDED} → declined; (d) application status in {CHECKOUT_EXPIRED, CAPACITY_FAILED_REFUNDING, CAPACITY_FAILED_REFUND_FAILED} → lead with attention flag; (e) application WAITLISTED with no waiting entry (skipped/removed) → left-lead: map to 'lead' with note 'waitlist removed'; (f) application DRAFT: if now > expires_at (7d TTL, models.py:105) → abandoned else lead; (g) application ABANDONED → abandoned; (h) trial_requests for the parent+child (match student_id when set, else prospective_child_name+dob): status approved/converted-unlinked with assigned occurrence end_at > now → trialing (date = occurrence start_at); approved with end_at <= now or status completed and no linked_application_id → trial_done; pending → lead; denied → lead with note; (i) nothing → never_enrolled. Prospective trial children have no student_id: emit a synthetic person row keyed (parent_user_id, normalized name, dob) and merge it with a Student on registration by the same key.
- R7 Returning flag. Whatever R1–R4 yields, set returning=true (and previous_left_at/reason from R5's rule) when any TERMINAL row or any departure event exists with occurred_at earlier than the newest LIVE row's created_at. Registration review and Add-to-roster show this flag.
- R8 Win-back clock (step 7). days_since_left = now − left_at from R5; eligible when state==left and no LIVE row and no win-back sent at that milestone (claim table keyed enrollment_id/student_id + milestone 30/60/90). Never send when returning re-activated.
- R9 Family / parent rollup. parent_state = the highest child state by precedence: active > pending_cancel > at_risk > on_hold_reclaiming > on_hold > paused > waitlisted > awaiting_approval > trialing > trial_done > lead > abandoned > declined > left > never_enrolled. Money overlay is independent of state: owes = sum(balance_due_cents) over invoices with status in {open, partially_paid} for parent_id across ALL periods (collections_read_model.py:424-447 leftover logic); has_credit = balance_for_parent > 0; card_on_file = has_saved_card; ladder = dunning_states status for open invoices. A parent with zero live children keeps users.status/membership active (returning-customer login); operational lists filter on the rollup, never on users.status.
- R10 Tabs. Active tab = {active, at_risk, pending_cancel}; On hold tab = {on_hold, on_hold_reclaiming, paused}; At risk tab = {at_risk} ∪ {any state with owes>0 and ladder in {dunned, suppressed}} ∪ {awaiting_approval older than 48h, trial_done older than N days, abandoned}; Left tab = {left} (from GetLeavingReport with widened DEPARTURE_EVENT_TYPES) plus left families with owes>0 or has_credit>0 flagged.

**Edge cases:**

- Child with one active and one paused enrollment → active (R1 wins); show a secondary chip 'paused in <class> until <date>'; do not count as paused in tab counts.
- Child with one held and one dropped row in the same session → on_hold; registration approve must treat the held row as a conflict (today it does not: mongo_enrollment_writer.py:436-442).
- Re-enrolled student (new active row after a terminal one, same student_id) → active + returning=true with previous_left_at/reason; students.status must not be consulted (it may still read 'inactive').
- Family with a balance but no live enrollment → parent_state=left, owes>0 → appears in Left tab AND Collections; overdue reminders (step 3) still apply because they key on parent_id, not enrollment_id; win-back email must mention the balance or be suppressed while owes>0 (owner decision needed).
- reclaim_pending → on_hold_reclaiming, transient; if it persists beyond 15 min (stalled), surface as attention; on finalize it becomes left with reason hold_reclaimed/hold_expired/hold_reclaim_orphaned — those event types are already in DEPARTURE_EVENT_TYPES.
- pending_cancellation_at set → pending_cancel with 'ends <date>'; note billing_sync already voided next month and disabled autopay at request time (self_cancel.py:578-590) so the money overlay may show autopay disabled while the child is still active.
- Trial completed but not registered → trial_done derived from assigned occurrence end_at <= now (no 'completed' writer exists, self_service.py:242); a later registration for a sibling must not convert this trial (LinkTrialConversion matches by parent, trial_requests.py:366-393).
- Application abandoned → DRAFT/CHECKOUT_PENDING past expires_at (no writer today; step 5 sweep) — until then derive from expires_at at read time so the funnel stops counting them as leads.
- Application WAITLISTED then promoted → the enrollment row exists so R1 wins, but the application row still says WAITLISTED with no enrollment_id; the derivation must not consult application status once an enrollment exists.
- Paused student promoted through the outbox path → status 'active' but deferral still active and autopay paused → shows active while billing is silently skipping; the money overlay should flag 'active deferral on active enrollment' as an attention item until the composition bug is fixed.
- Parent self-cancel (immediate) → row status 'cancelled' (legacy spelling) and event_type 'cancelled' → must map to left; today it is invisible to the leaving report.
- Student hand-set to 'cancelled' in students.status with live enrollments → active (status ignored); waiver compliance must stop excluding them (mongo_admin_waiver_repo.py:152-162).
- Parent disabled via /admin/users while children are active → children stay active; flag 'parent login disabled' on the family header; do not derive left from users.status.
- Prospective trial child (no Student) → synthetic person row; on registration approve, match by (parent_user_id, normalized name, dob) to link the trial and avoid a duplicate lead card.
- Student with attendance only on cancelled occurrences → those occurrences are excluded from the at_risk window (status != cancelled), so a run of cancelled classes never produces at_risk.
- Held family during an occurrence cancel → no event and no credit by design (cancel_session_occurrence.py:68-76); timeline for on_hold students will lack that date.
