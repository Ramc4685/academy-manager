# Parent Portal Attractive Home Design

## Context

The parent portal already has working routes for dashboard, children,
attendance, payments, progress, waivers, onboarding, and checkout return.
The current `/parent/dashboard` is useful but light: academy greeting,
student/enrollment counts, active sessions, quick links, and academy contact.

Several parent pages already use the newer Rally visual system, especially
dashboard, children, and progress. Payments, attendance, and waivers are more
neutral, but this design intentionally limits the first pass to the home
dashboard only.

Existing parent API data available to the frontend:

- academy display name, contact fields, and logo URL;
- children;
- enrollments;
- attendance records;
- coach progress notes;
- payments and credits;
- waiver status;
- schedule data per child;
- curriculum progress summary/passport data when the existing feature flag
  enables it.

The first pass is frontend-only. It must not add a backend `/parent/home`
endpoint and must not change SaaS tenant resolution or backend boundaries.

## Goal

Make the parent portal attractive by making `/parent/dashboard` feel like a
daily progress companion for parents, not only a navigation hub.

The first impression should communicate:

1. My child is growing here.
2. I know what is next.
3. I know whether anything needs action.
4. This academy app feels polished and trustworthy.

## Chosen Approach

Use **Progress Home Recomposition**.

Rebuild the dashboard around one cohesive flow:

1. family or selected-child progress hero;
2. child selector pills;
3. compact skill/progress metrics;
4. latest coach note;
5. next class or enrollment context;
6. strongest action card;
7. recent activity;
8. academy contact/brand footer if useful.

This uses existing frontend queries only. It avoids broad parent-app restyling
and avoids backend work.

## UX And Visual Hierarchy

The home page should lead with progress.

For one-child families, the hero is personal and direct: selected child name,
level/pathway progress when available, and an avatar or logo-backed visual
treatment.

For multi-child families, use a smart default:

- show the family context and academy identity;
- render child pills near the top;
- select the first active child by default;
- let the selected child drive the hero, metrics, note, next class, and recent
  activity filtering.

Primary hierarchy:

1. **Hero:** academy identity, selected child, progress percentage or fallback
   message, pathway/level label when available.
2. **Metrics:** mastered, learning, test-ready/ready, or neutral attendance and
   session metrics when skill data is unavailable.
3. **Latest coach note:** newest note for selected child, with coach/date.
4. **Next class:** nearest schedule entry when available; otherwise active
   enrollment summary.
5. **Action card:** one strongest item only: waiver needed, payment issue,
   credit available, no child registered, no active enrollment, or onboarding
   continuation.
6. **Recent activity:** three concise rows from attendance, payment, and coach
   note data.

## Theme And Motion

Use the existing app theme as the base:

- Rally paper, ink, line, cobalt, and volt tokens;
- current parent shell spacing and mobile-first width;
- existing shimmer/loading style.

Use tenant identity that is already available on parent routes:

- `academy.display_name`;
- `academy.logo_url`.

Do not depend on tenant `brand_color` in the first pass. Admin settings persist
`brand_color`, but the parent academy endpoint does not currently expose it.
Adding that field is a later backend/API enhancement.

Micro animations should be subtle and functional:

- hero/avatar entrance;
- progress-bar fill;
- staggered card reveal;
- active child pill transition;
- gentle pulse only for genuinely new or urgent items.

All motion must respect `prefers-reduced-motion` and must not cause layout
shift.

## Data Flow

The dashboard composes existing queries:

- `getParentAcademy()` for academy name/logo/contact;
- `listParentChildren()` for child pills and selected-child fallback;
- `listParentEnrollments()` for active enrollment summaries;
- `listParentAttendance()` for attendance summaries and activity rows;
- `listParentProgress()` for latest coach notes;
- curriculum progress summary/passport calls where the existing feature flag
  allows them;
- `listParentPayments()` and `listParentCredits()` for compact billing status;
- `getParentCurrentWaiver()` for waiver action status.

Display-only facts can be derived client-side:

- selected child;
- latest child-specific coach note;
- next class-like summary;
- recent activity rows;
- strongest action card;
- skill progress fallback state.

Business truth must remain backend-owned. The frontend can format and compose
already-authorized parent data, but it must not invent billing, waiver, or
progress facts.

## States And Guardrails

The dashboard must remain useful when data is incomplete.

- **Loading:** skeleton hero, metric tiles, and cards using existing shimmer.
- **No children:** hero becomes a warm registration prompt with academy identity
  and a primary "Register a child" action.
- **No progress data:** keep the child hero, but show "First skills will appear
  after coach assessment" or equivalent neutral copy.
- **No coach notes:** show "Coach notes will appear here" as a calm empty card.
- **No next class:** show active enrollment summary when available; otherwise
  guide to onboarding/children.
- **Partial errors:** failed payments, waivers, or progress calls must not blank
  the whole dashboard.
- **Reduced motion:** disable or simplify all decorative motion.

## Files Likely Affected

- `frontend/app/(parent)/parent/dashboard/page.tsx`
- `frontend/lib/api/parent.ts` only if an existing type needs a small
  frontend-only adjustment.

No backend changes are planned for this pass.

## Out Of Scope

- Redesigning Payments, Attendance, Waivers, Children, Progress, Onboarding, or
  the parent shell.
- Adding `/api/v2/parent/home`.
- Adding parent `brand_color` support.
- Adding a parent inbox.
- Changing route names or redirects.
- Changing SaaS tenant resolution.

## Risks

- The page will make several independent API calls. It needs careful partial
  loading and partial error handling.
- Curriculum progress data is feature-flagged, so the hero cannot depend on it
  always being available.
- Parent `brand_color` is not available without backend scope.
- The branch already contains unrelated feature work; implementation must stay
  scoped to parent dashboard files and avoid sweeping unrelated changes into
  commits.

## Verification

Planned checks for implementation:

1. `cd frontend && pnpm typecheck`
2. `cd frontend && pnpm lint`
3. Browser smoke at `http://blno.localhost:3001/parent/dashboard`
4. Mobile-width check for text fit, animation behavior, and no obvious
   overlap.
5. Spot-check loading, empty, partial-error, one-child, and multi-child states
   where practical.
6. Record verification in
   `docs/test-results/active/2026-06-07-parent-portal-attractive-home.md`.

