# BLNO staging launch-readiness sweep

Fixes the P0/P1 findings from `docs/reviews/2026-07-02-code-review-ux-walkthrough.md` plus the remaining launch gaps, verified end-to-end on the local SaaS staging stack as parent, coach, and admin.

## Payments
- Shared parent-safe error mapper (`frontend/lib/api/payment-error.ts`) — raw backend detail never reaches parents; portal-prerequisite hint scoped to the portal action; `Billing.CheckoutCreationFailed` mapped to accurate "academy payments not set up yet" copy.
- ACH checkout polling stops on `verification_required`/`verification_pending` + 5-minute hard cap.
- Connect onboarding `refresh_url`/`return_url` validated against the redirect allowlist.
- Payment history labeled via payment_allocations→invoice lookup ("Tuition · Apr 2026"); invoice periods render "Jun 2026"; "Pause" → "Pause enrollment" with future-only resume date.
- Admin gateway settings expose Connect account status; `POST /admin/academy/gateway/stripe/connect-link` starts Express onboarding. Stripe test-mode setup documented in `docs/runbooks/saas-local-staging.md` (keys go in `.local/saas-staging.env`).

## Coach
- Dead "Message parents" / "I can't attend" day-hub buttons removed (e2e asserts absence).
- "Mark all present" bulk attendance (existing bulk endpoint); `/coach/today` hydrates recorded `attendance_status` so reloads and bulk marking survive the offline caches; bulk 409 auto-refetches server truth; `aria-pressed` + visible ✓.

## Admin
- Billing-health repos: unbounded N+1 → single `$lookup` aggregations with limits; dunning `claim_next_due` filter pushed into Mongo; silent dunning-worker skip now logs a warning.
- Billing Health page: neutral "No reconciliation run yet" state, active-only dunning count, `Next:`/`Terminal:` prefixes, expandable reconciliation notes.
- Dues: dead Stage column removed (`followup_stage` never populated by backend).
- Dashboard: "Revenue (month to date)" with last-month hint.

## Timezone
- `frontend/lib/format/academy-time.ts`: schedule times render in the academy timezone with an explicit label; applied to parent children/dashboard; academy timezone exposed on `ParentAcademyView`.

## Data & scripts safety
- `scripts/dev/mongo_guard.py`: shared local-only Mongo guard (rejects multi-host seed lists, `mongodb+srv`, non-local hosts); destructive cleanup script gains the guard and stops defaulting to the prod DB name.
- Seed: `students.parent_id` moved to `$set` (emulator resets orphaned the whole parent portal); orphaned memberships cleaned; pathway seed prints JSON so `program_id` parses (was a silent dict-repr failure that skipped every placement); truncated-ULID id collisions fixed; all active students placed at Level 1.
- Onboarding: returning parents' `parent_profile` carried into new applications ("+ Add child" no longer asks them to retype their details).
- `launch_readiness_audit` expects the latest per-collection validators (0138/0140/0144) — audit passes against a fully migrated DB.

## Tests
- Backend: `pytest v2/tests` → **2057 passed**; ruff format+check clean.
- Frontend: typecheck + lint clean; node tests **60/60**; coach e2e **9 passed** (incl. previously flaky day-hub spec, now with a 90s journey timeout).
- Launch-readiness audit vs staging: **pass**.
- Live staging walkthroughs as parent/coach/admin recorded in `docs/test-results/archive/2026-07-02-blno-launch-readiness-fixes.md`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
