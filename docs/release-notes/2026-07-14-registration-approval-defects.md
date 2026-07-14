# Registration approval defects

PR: #302

## What changed

- **Approval no longer shows a false error after succeeding.** The admin registration page keeps the successful approval response in the detail cache and refreshes only the exact registration list, avoiding the redundant detail request that previously replaced a successful result with "Could not load registration."
- **Enrollment dates now reflect the parent's registration date.** New approvals copy the onboarding application's `created_at` value into `enrolled_at`. Existing approved registrations with a missing date are backfilled by migration `0146_registration_enrollment_dates`. The roster displays **Not recorded** for genuinely missing dates instead of converting a null timestamp to December 31, 1969.
- **Already-enrolled children can no longer create duplicate registrations.** Parent onboarding matches children within the authenticated parent and tenant using normalized name and date of birth, rechecks eligibility when checkout starts, and blocks a new registration when that child already has an active enrollment. Ambiguous same-name legacy records are routed to manual academy review instead of being guessed. The admin pending list hides stale duplicates and approval/waitlist actions repeat the check server-side.
- **Concurrent admin decisions and duplicate applications are single-winner.** Approval, waitlist, and rejection atomically claim a pending application before creating artifacts. Registration-created student, enrollment, and lifecycle-event identifiers are deterministic and application-owned; expiring, token-fenced review/child leases plus a post-claim enrollment check prevent two applications for the same child from approving into different sessions without leaving permanent locks after a worker restart. Stale work is fenced from releasing or finalizing a replacement worker's claim. Approval also rejects a session override that differs from the parent's selected session.
- **Post-approval side-effect failures no longer reverse a successful decision.** If trial-conversion linking fails after approval is committed, the failure is logged for follow-up while the approved registration remains visible as successful.
- **The parent confirmation now says `Child added`.** It uses the submitted child's first name, for example, "Kavan has been added. An admin will confirm the enrollment shortly." It no longer treats a checkout return or `PENDING_APPROVAL` status as proof that payment was received.
- **Tenant attribution remains request-scoped.** Registration approval and waitlist writes resolve the current academy from the request context rather than capturing a default academy at application startup.

## Deploy notes

Migrations `0146_registration_enrollment_dates` and `0147_registration_student_lock` run automatically when `V2_RUN_MIGRATIONS_ON_BOOT=true`. The first only fills `enrolled_at` when an approved onboarding application has a valid `created_at` date and the linked enrollment date is currently missing. The second adds a unique partial index used only by new registration-created active or paused enrollments, so legacy rows are unaffected. No environment changes or manual data steps are required.

## Verification

- Backend focused registration, tenancy, concurrency, and crash-recovery tests: **54 passed**.
- Full backend suite after security-review fixes: **2,429 passed** with 23 existing warnings.
- Ruff formatting/lint and all 5 import-linter contracts: **passed**.
- Frontend typecheck and production build: **passed**; lint reported 0 errors and 6 pre-existing warnings.
- Admin approval Playwright regression: **passed** on mobile Chromium.
- Parent/QA Playwright suite: **20 passed** across mobile Chromium and WebKit.
- Authenticated BLNO Docker staging check on iPhone WebKit: **passed** with the expected dynamic child name, zero occurrences of the old payment heading, and zero browser-console errors or warnings.

## Risk / rollback

The main behavioral risk is that older imported children with missing dates of birth may need manual academy resolution when more than one same-name record exists. This is intentionally conservative to avoid modifying or enrolling the wrong child. The staging seed's broader launch-readiness audit also reports three pre-existing invoice-balance mismatches that are unrelated to this registration change.

Roll back the application commit to restore the prior registration behavior. Migration `0146` is additive and safe to leave applied because it only fills previously missing enrollment dates from the corresponding approved application timestamp. Migration `0147` may also remain because its index only applies to the new registration lock field; drop `uq_registration_active_student_lock` only if the new workflow is permanently retired.
