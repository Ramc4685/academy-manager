# CourtMastr QA Defects - 2026-05-26

Source: full QA walkthrough summary provided on 2026-05-26.

## QA-001 - Missing academy owner signup path

- Severity: Critical
- Surface: Landing page, registration
- Observed: Public navigation exposes sign-in and parent registration, but no self-serve academy owner/admin signup CTA.
- Impact: New paying academy customers cannot start from the public site.
- Status: Open
- First remediation: Add a visible owner CTA that routes to a planned owner lead/signup flow, or explicitly labels owner onboarding as sales-assisted.

## QA-002 - Child date of birth control is broken

- Severity: Critical
- Surface: `/parent/onboarding`, child step
- Observed: Date of birth presents native spinbutton/calendar behavior, gets stuck at zero values, and JS-set values are not visibly reflected.
- Impact: Parent onboarding blocks at child profile entry.
- Status: In progress
- First remediation: Replace native date picker usage with a stable text date field that accepts `YYYY-MM-DD` and preserves the API payload shape.

## QA-003 - Native date picker month panel navigates away

- Severity: Critical
- Surface: `/parent/onboarding`, child step
- Observed: Clicking the native date picker month selection panel navigates away from onboarding.
- Impact: Parent loses onboarding context.
- Status: In progress
- First remediation: Remove reliance on the native date picker popup for this flow.

## QA-004 - Skill level dropdown is not reliably interactable

- Severity: High
- Surface: `/parent/onboarding`, child step
- Observed: Native skill `<select>` interaction produced `CDP error: DOM.getBoxModel`.
- Impact: Automated and potentially real-user interaction with child profile can fail.
- Status: In progress
- First remediation: Replace the native select with explicit button/radio choices that are stable under browser automation and touch input.

## QA-005 - Wrong-role admin route redirects silently

- Severity: High
- Surface: `/admin`, `/admin/*`
- Observed: Parent user visiting admin routes is redirected to `/parent/payments` without an access-denied explanation.
- Impact: Users cannot tell whether access is missing, the route failed, or the app changed pages unexpectedly.
- Status: In progress
- First remediation: Carry an access-denied reason to the target persona home and render a clear alert.

## QA-006 - Wrong-role coach route redirects silently

- Severity: High
- Surface: `/coach`, `/coach/*`
- Observed: Parent user visiting coach routes is redirected to `/parent/payments` without an access-denied explanation.
- Impact: Same silent auth failure as admin routes.
- Status: In progress
- First remediation: Reuse the wrong-role redirect alert for all persona route guards.

## QA-007 - Billing portal button silently no-ops

- Severity: High
- Surface: `/parent/payments`
- Observed: Billing portal button click stays on the same page with no redirect and no visible error.
- Impact: Parent cannot self-serve Stripe billing management and gets no recovery guidance.
- Status: In progress
- First remediation: Surface portal mutation failures and invalid/missing redirect URLs in an inline alert.

## QA-008 - Forgot password is inline-only

- Severity: Medium
- Surface: `/login`
- Observed: Forgot password shows inline "Enter your email first"; no dedicated reset page.
- Impact: Recoverability is functional but not clearly discoverable.
- Status: Open
- First remediation: Decide whether to add a dedicated reset page or improve inline copy/state.

## QA-009 - Parent progress and children show raw loading text

- Severity: Medium
- Surface: `/parent/progress`, `/parent/children`
- Observed: Pages briefly show raw "Loading..." before content.
- Impact: Perceived polish and hydration quality are lower.
- Status: Open
- First remediation: Replace raw loading text with compact skeleton states.

## QA-010 - Landing copy narrows market perception

- Severity: Low
- Surface: Landing page
- Observed: Hero says "Run your badminton academy" and footer strip says "Built for USA".
- Impact: Product appears limited to badminton and US-only operations despite broader racquet-sports positioning.
- Status: Open
- First remediation: Broaden public copy to racquet sports and region-ready wording.
