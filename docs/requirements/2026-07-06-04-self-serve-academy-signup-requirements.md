# Self-Serve Academy Signup — Requirements

Date: 2026-07-06 · Roadmap item 8 of 9 · [Index](2026-07-06-00-roadmap-index.md)
**Flagged in the competitive analysis as the single biggest go-to-market gap.**

## Problem

Jackrabbit's instant, no-sales-call free trial is credited as its acquisition
engine (7,000+ customers); TeamUp, Omnify, and ClassManager all convert on
"self-serve signup, first booking within minutes." Even the demo-led competitors
(iClassPro, Sawyer, Amilia) still let a prospect start a conversation without
manual backend provisioning. We currently have exactly one path to create a new
academy tenant: a platform operator manually calling
`POST /api/v2/platform/bootstrap`. There is no way for a prospective customer to
create their own academy, even in a sandboxed/trial state, without a human on our
side doing it for them. This directly blocks any self-serve growth motion and is
the largest single gap identified in the competitive analysis.

## Current State (codebase evidence)

- `backend/v2/interfaces/platform/` — bootstrap route
  (`/api/v2/platform/bootstrap`) creates an academy, provisions the first admin
  user, and seeds curriculum, but requires a `platform_admin`/`platform_support`
  role to call it. No public/unauthenticated or self-serve-authenticated path
  exists.
- Identity model (`backend/v2/contexts/identity/`) already supports the right
  shape for this: `User` (global), `AcademyMembership` (per-academy role), and
  `PlatformRole` (cross-tenant) — a self-serve flow can create a `User` +
  `AcademyMembership(role=admin)` + a new academy record without new identity
  primitives.
- Tenant resolution (subdomain/custom domain/header-based, per earlier inventory)
  already exists — a self-serve flow needs to allocate a subdomain slug, not
  invent tenant resolution from scratch.
- Firebase auth (email/password + Google Sign-In) is already the auth mechanism for
  all personas — self-serve signup can reuse it directly (create a Firebase user,
  then the academy + admin membership).

## Goals

- A prospective customer can create their own academy account without any human
  intervention on our side: choose a subdomain, create their own login, and land
  in a working (possibly trial-limited) admin console within minutes.
- Preserve the existing manual bootstrap path for platform-operator-assisted
  provisioning (white-glove onboarding, migrations) — this is additive, not a
  replacement.
- Trial/limited state should be enforceable (e.g., cap on students, cap on coaches,
  time-boxed trial) without requiring separate code paths per tenant — a
  plan/tier flag on the academy record, checked by existing authorization/limits
  logic.

## Non-Goals

- No self-serve billing/plan upgrade flow in this slice (i.e., collecting the
  academy's own subscription payment to us) — that's a distinct payments-for-SaaS
  project, separate from parent-facing tuition billing. This slice only covers
  tenant creation and trial gating, not our own revenue collection from academies.
- No automated data-migration tooling from a competitor's export (iClassPro/
  Playbypoint both market migration assistance) — that remains a manual,
  white-glove service for now.

## Requirements

### R1. Public signup entry point
- A public (unauthenticated) marketing/signup page collects: academy name, desired
  subdomain slug, admin's name/email, password (or Google Sign-In).
- Subdomain slug availability is checked and validated in real time (matches
  existing subdomain resolution rules — same character/length constraints already
  enforced server-side for tenant routing).

### R2. Academy + admin provisioning
- On submission: create the academy record (in `trial` plan state), create the
  Firebase user if not using Google Sign-In, create the `User` + first
  `AcademyMembership(role=admin)`, seed a minimal default curriculum/program (reuse
  existing bootstrap seeding logic rather than duplicating it) so the new admin
  isn't dropped into a completely empty console.
- Send a verification/welcome email (existing communications infrastructure can be
  reused for the welcome email; actual email verification enforcement is an
  auth-layer decision, see Open Decisions).

### R3. Trial/plan gating
- Academy record carries a `plan_tier` (`trial` | paid tiers, names TBD by
  business) and `trial_expires_at`.
- Existing authorization checks gain a plan-tier-aware limit check (e.g., max
  active students, max coaches) that reads from a per-tier limits config —
  centralize this rather than scattering ad hoc checks per endpoint.
- Trial expiry behavior (read-only lockout vs. hard block vs. grace period) is a
  business decision — see Open Decisions.

### R4. Guided first-run experience
- Directly motivated by the competitive research finding that onboarding
  difficulty (steep learning curve) is the single most common complaint across
  reviewed competitors (Amilia, iClassPro, TeamSnap). New admin's first login
  presents a checklist: add a coach → create first session → connect Stripe
  (existing Connect onboarding flow) → invite first parent. Checklist state is
  tracked so it doesn't nag a returning admin who's already done these steps.

### R5. Anti-abuse basics
- Rate-limit signup attempts per IP/email.
- Subdomain slugs are validated against a reserved-word list (avoid squatting on
  `admin`, `api`, `www`, etc. — check whatever reserved list the existing tenant
  resolution middleware may already enforce, extend if it doesn't).

## Data Model Changes

### `academies` (extend existing academy record)
```text
plan_tier: "trial" | <paid tier names, TBD>
trial_expires_at: datetime | null
signup_source: "self_serve" | "platform_bootstrap"
onboarding_checklist_state: { added_coach: bool, created_session: bool,
  connected_stripe: bool, invited_parent: bool }
```

### New `plan_tier_limits` (config, not per-academy)
```text
tier: "trial" | <paid tiers>
max_active_students: int | null
max_coaches: int | null
max_academies_per_owner: int | null   # anti-abuse
```

### New `signup_attempts` (anti-abuse audit/rate-limit)
```text
attempt_id
ip_address
email
subdomain_requested
created_at
outcome: "succeeded" | "rejected_duplicate_subdomain" | "rejected_rate_limited"
```

## Dependencies

- None on other roadmap items technically, but is the largest single effort in
  the roadmap — sequence based on business priority (growth impact) rather than
  technical dependency, per the index's sequencing note.
- Reuses existing bootstrap seeding logic (`/api/v2/platform/bootstrap`
  composition) rather than duplicating it — confirm that logic is refactorable
  into a shared use case callable from both the platform-operator path and the
  new self-serve path.

## Open Decisions

1. Is email verification required before the new academy is usable, or can the
   admin start immediately and verify async? (Affects whether R2's welcome email
   is a hard gate or a nice-to-have.)
2. Trial expiry behavior: hard lockout, read-only degrade, or automatic downgrade
   to a free/limited tier? Business decision, not a technical one.
3. Does self-serve signup collect a credit card upfront (even if not charged during
   trial) to reduce abuse/spam signups, matching Jackrabbit's no-card model or a
   stricter posture?
4. Max academies per signup email/owner — is one person allowed to spin up
   multiple trial academies, and if so, how many before it's flagged for review?
5. Does the guided first-run checklist (R4) block access to other features until
   complete, or is it dismissible/advisory only? (Recommendation: advisory —
   don't gate functionality, just surface the checklist.)

## Acceptance Criteria / Test Cases

- A prospective customer completes the public signup form and lands in a working
  admin console with a seeded default curriculum, without any platform-operator
  action.
- Subdomain collision is rejected with a clear message before submission
  completes (real-time availability check).
- The existing platform-operator bootstrap flow (`/api/v2/platform/bootstrap`)
  continues to work unchanged for white-glove onboarding.
- A trial academy that exceeds its configured student/coach limit is blocked from
  adding more, with a clear message, not a silent failure.
- The onboarding checklist correctly reflects completed steps and does not
  reappear once dismissed/completed.
- Signup rate-limiting rejects abusive rapid-fire attempts from the same IP/email
  without blocking legitimate single attempts.
