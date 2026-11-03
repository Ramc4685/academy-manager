# In-app account deletion (mobile slice M5) — design

Status: D1 (request endpoint) built 2026-11-03 with the proposed defaults for decisions 7-9: a balance does not block, a coach with upcoming classes is refused, 14-day window. D2-D5 not started. Owner decisions are marked **[owner]**.
Parent plan: `docs/plans/2026-11-02-mobile-apps.md` (M5).

## Why

- **Apple 5.1.1(v)**: an app that lets people sign in must let them start deletion of
  the account *inside the app*. Deactivating, or "email us", is not enough. Apps that
  offer Sign in with Apple must also revoke the user's Apple tokens on deletion.
- **Google Play (User Data policy, account deletion)**: the same in-app path, plus a
  **web link** where someone can request deletion without reinstalling the app. That
  URL goes in the Play Console data-safety form.
- Both allow keeping data we are legally required to keep (accounting, fraud, legal
  holds), as long as the policy says so.

## What exists today

Short answer: **no self-service deletion for any persona.** What does exist:

| Piece | Where | What it does |
|---|---|---|
| Admin deactivate | `frontend/app/(admin)/admin/users/[userId]/page.tsx`, `mongo_user_repo` status update | Sets the user/membership `disabled` and flips the Firebase account's `disabled` flag (`FirebaseAdminAdapter.set_user_disabled`, #785). Reversible. Deletes nothing. |
| Firebase hard delete | `FirebaseAdminAdapter.delete_user` | Only used to roll back a half-created user in `mongo_user_repo` create. No route reaches it. |
| Governance deletion requests | `contexts/platform/governance`, `interfaces/platform/governance_routes.py` (`POST /tenant-deletions`, `POST /student-data-deletions`) | **Platform-operator only.** Writes a `pending_review` row and stamps `governance_deletion_status` on the academy or student. Request-only: nothing is deleted or anonymised. |
| Policies | `SoftDeletePolicy`, `RetentionPolicy`, `PIIHandlingPolicy` (governance `domain/models.py`) | `hard_delete_allowed=False`, `preserve_financial_records=True`, `preserve_audit_logs=True`; financial and audit retention 2555 days (7 years); parent PII fields `full_name, email, phone, billing_contact`; student PII `full_name, date_of_birth, medical_notes, parent_contact`. |
| Cascade checklist | `docs/policy/governance-deletion-cascade.md` (#788) | 11-row list of what an executor owes per student. **No executor exists.** |
| Retention draft | `docs/policy/data-retention.md` | Draft; says no deletion controls ship until approved. Its open decisions overlap the ones below. |
| Privacy page | `frontend/app/(marketing)/privacy/page.tsx` | Says "send requests to support@marvylabs.com". Marked draft. |

So the building blocks are there (Firebase disable/delete, policy objects, a request
row pattern, a written cascade), but no user can start deletion and nothing executes it.

## What hangs off a user

A user is a Firebase account (`uid` = `users.user_id`), global across academies, with
one `academy_memberships` row per academy. Parents own students; coaches own sessions
and payroll lines.

| Data | Collection(s) | Key to the user | Proposed action |
|---|---|---|---|
| Firebase Auth account | Firebase | `uid` | Disable at request, **delete** at execution |
| Sign in with Apple grant | Apple | Apple `sub` | **Revoke** (client sends a fresh authorization code; Firebase `revokeAccessToken`) |
| User profile | `users` | `user_id` | **Anonymise**: name → "Deleted user", email → `deleted+<hash>@invalid`, phone null, `status: deleted`. Keep the row so foreign keys still resolve. |
| Memberships | `academy_memberships` | `user_id` | Status `removed` in every academy |
| Push devices | `push_devices` (M2 branch) | `user_id` | **Delete** |
| Sign-in helpers | `parent_magic_links`, `login_attempts`, `verification_email_cooldowns`, `idempotency_keys` | user id / email | **Delete** |
| Email preferences | `email_preferences` | user id / email | **Delete** |
| Email suppressions | `email_suppressions` | email | **Keep** (stops mail to a bounced/complained address); consider storing a hash only |
| Students (children) | `students` | `parent_id` / `parent_user_id` | **[owner]** anonymise or delete; minors' PII (`full_name`, `date_of_birth`, `medical_notes`) must not survive in clear text |
| Family contacts, notes, follow-ups | `family_contacts`, `family_details`, `family_notes`, `family_follow_ups`, `family_contact_log` | parent id | **Delete** free text and second-guardian contact details |
| Enrollments, roster, waitlist, makeups, pause/trial requests | `enrollments`, `occurrence_roster_entries`, `waitlist`, `makeup_requests`, `pause_requests`, `trial_requests`, `scheduled_enrollment_actions` | student / parent id | **Withdraw** live enrollments through the enrollment use case (it calls `billing_sync`, so no future invoices), then keep rows pointing at the anonymised student |
| Attendance, absences | `attendance`, `absence_notices`, `coach_attendance` | student id | Keep counts (coach payroll depends on them); **delete** absence free-text reasons |
| Progress, certificates, notes | `student_skill_progress`, `student_level_progress`, `skill_certificates`, `progress_notes`, `coach_skill_notes`, `level_up_recommendations`, `session_feedback` | student id | **[owner]** delete, or keep anonymised for academy stats |
| Waivers | `waiver_signatures`, `waiver_acceptances`, `waiver_artifacts` | parent / student id | **[owner]** retention window; a signed release of liability is often kept for the statute of limitations. Default proposal: keep, restrict access to owner role |
| Messages | `messages`, `message_deliveries` | sender / recipient id | **[owner]** redact bodies the user wrote, or keep with sender shown as "Deleted user" |
| Notification send logs | `parent_digest_sends`, `parent_report_card_sends`, `absence_notice_sends`, `win_back_notice_sends`, `enrollment_hold_notice_sends`, `invoice_contact_email_sends`, `email_provider_events` | email / user id | Redact email; keep the send fact |
| CRM leads | `crm_contacts` | `converted_parent_id`, `linked_user_id`, email | **Delete** the contact row (no accounting value) |
| Onboarding | `onboarding_applications` | user id | **Delete** |
| Invoices, lines, payments, allocations, ledger, credits, refunds, disputes | `invoices`, `invoice_lines`, `payments`, `ledger_payments`, `payment_allocations`, `account_credit_ledger`, `credit_applications`, `payment_disputes`, `subscriptions` … | parent / payer id | **Keep** (7 years, `preserve_financial_records`). Redact contact snapshot fields (name, email) only where a field copies them; the id link to the anonymised user stays |
| Stripe customer + saved cards | `parent_billing_customers`, `autopay_consents`, Stripe | `stripe_customer_id` | **Cancel autopay**, detach payment methods; **[owner]** delete the Stripe customer or keep it for refunds/disputes |
| Coach payroll | `coach_rates`, `payout_periods`, `payout_period_lines`, `payouts`, `coach_payout_snapshots` | `coach_id` | **Keep** (financial) |
| Sessions taught | `sessions`, `session_occurrences` | `coach_id` | Keep; the coach must be reassigned first (existing `COACHING_ROLES` rule) |
| Audit logs | `audit_logs`, `billing_audit_log`, `platform_audit_events`, governance audit | actor id; `before`/`after` snapshots | **Keep** (`preserve_audit_logs`). Note: `user.created` snapshots copy email, name and phone; **[owner]** redact those snapshot fields or accept them under the audit retention |
| Sentry | Sentry | `user.id` only (`send_default_pii=False`) | Nothing; events expire on Sentry's retention |

## Proposed flow

1. **Request (in app and on the web).** Profile → "Delete account" on
   `/parent/profile` and `/coach/profile`. The screen says what is deleted, what is kept
   and why (invoices and payments for 7 years), and shows any blocker. The person
   re-authenticates (Firebase ID token `auth_time` under 5 minutes) and types DELETE.
   In the iOS app with an Apple-linked account, the client also collects a fresh Apple
   authorization code for revocation.
2. **`POST /api/v2/me/account-deletion`** (any persona, no academy scope). Blockers:
   - sole **owner** of an academy: refuse, point to tenant deletion (that is a
     different, operator-reviewed flow);
   - coach with sessions still assigned: **[owner]** refuse until an admin reassigns, or
     accept and alert the admin.
   Otherwise, in one request, immediately:
   - disable the Firebase account (`set_user_disabled(uid, True)`, which also kills
     refresh tokens) and revoke the Apple grant;
   - mark every membership `removed`; delete `push_devices` rows;
   - write an `account_deletion_requests` row (`user_id`, `requested_at`,
     `execute_after`, academy ids, status `scheduled`) and one audit row per academy;
   - email a confirmation to the address on file (sent *before* anonymisation).
   The person is signed out. From their side the account is gone.
3. **Execute after a grace window [owner]** (proposal: 14 days, cancellable only by
   contacting the academy, which re-enables via the existing admin path). A scheduled job
   (registered in `settings.sentry_cron_jobs`, per the cascade doc's rules) walks the
   table above: withdraw enrollments through enrollment use cases, cancel autopay and
   detach cards through billing, anonymise students per the decision, anonymise the
   `users` row, delete CRM/helper rows, then `delete_user(uid)` in Firebase last. Each
   context does its own step through its own use case (the governance context never
   writes another context's collections). Every step is idempotent so a crash resumes.
4. **Admins see it.** The family's admin page shows "Deleted by the parent on <date>";
   the outstanding balance, if any, stays visible and collectable offline.
5. **Web deletion link for Google Play.** A public page (`/account-deletion` on the
   product host) explains the steps, links to sign in and go to Profile → Delete
   account, and gives the support address for people who can no longer sign in.

Shared Firebase account across academies: deletion is global (the store rules talk about
the account, not a membership). Leaving one academy stays an admin action.

## Owner decisions needed

1. **Retention of financial records**: confirm 7 years for invoices, payments, ledger,
   payouts (the code already says 2555 days). Do we redact the payer name on kept
   invoices, or keep it (an invoice normally carries the customer name)?
2. **Children's records**: on a parent's deletion, delete students outright, or keep
   anonymised rows ("Student 4F2A") so academy attendance/progress stats stay whole?
   Medical notes and date of birth are deleted either way.
3. **Second guardian**: if another guardian on the family still has an account, do the
   children stay with them (no student anonymisation)?
4. **Waivers**: retention window for signed waivers after an account is deleted.
5. **Messages**: redact what the person wrote, or keep it under "Deleted user".
6. **Stripe customer**: delete it at Stripe, or keep it (with cards detached) for
   refunds and disputes during the retention window.
7. **Unpaid balance**: allow deletion with a balance owed (recommended; Apple does not
   allow blocking deletion on a debt, and the invoice survives), and notify the admin.
8. **Coach with assigned sessions**: block until reassigned, or accept and alert.
9. **Grace window** length (proposal 14 days) and whether the person can undo it.
10. **Audit snapshots** that copy email/name/phone: redact or keep under audit retention.
11. **Support address** printed on the deletion page and in the privacy policy
    (`support@marvylabs.com` today), and whether Marvy Labs is the data controller
    named there or the academy is (see the store-listing doc, "Legal entity").

## Slices

Each is one PR with a release note; D1 to D3 must all land before the first store
submission (Apple reviews the deletion flow on the build it reviews).

| # | Slice | Depends on |
|---|---|---|
| D1 | Backend request: `account_deletion_requests` store + migration, `POST /api/v2/me/account-deletion` (re-auth check, owner/coach blockers, Firebase disable, membership removal, push-device delete, audit, confirmation email). Real-Mongo contract test and interface test | Decisions 7, 8, 9 |
| D2 | Frontend: "Delete account" on parent and coach profile, explainer + typed confirm, re-auth prompt, Apple revocation on iOS (`@capacitor-firebase/authentication` returns the authorization code), signed-out landing | D1 |
| D3 | Executor: scheduled job + per-context anonymisation use cases (identity, enrollment/students, billing customer/autopay, crm, communications, waivers per decision), Firebase delete last. Update `docs/policy/governance-deletion-cascade.md` rows in the same PR | D1, decisions 1-6, 10 |
| D4 | Admin visibility (family page banner, deletion list) and the public `/account-deletion` page for the Play form | D1 |
| D5 | Privacy policy rewrite: data list, retention table, deletion steps, controller and contact (see store-listing doc) | decisions 1, 4, 11 |

Out of scope here: the platform-operator tenant deletion executor (#788) — D3 builds the
per-context anonymisers it will reuse.
