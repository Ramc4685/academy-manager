# Batch 9b: parent shell consistency

PR: #0

## What changed
- Fixes #843 — Parent bottom nav now carries a fifth tab, Requests, and the header carries a 44px Profile link, so makeup requests and profile edits are reachable from the shell instead of a card low on Home.
- Fixes #843 — The four different pay treatments (gold gradient, volt outline, dark ink, red/amber pill) collapse onto the design-system primary cobalt `Button` for Pay balance, per-invoice Pay, Set up autopay, and the Home balance-banner Pay.
- Fixes #843 — Billing portal and View detail controls now meet the 44x44 touch-target minimum.
- Fixes #843 — Pause-enrollment moved off the Payments page into a shared `PauseEnrollmentForm` mounted on Children next to Cancel; Payments now links there instead of hosting its own pause flow.
- Fixes #843 — Off-palette purple/pink stops in avatar gradients, progress accents, and calendar child colours became Rally/DS hues; the waivers signer input gets a visible cobalt focus ring.
- Fixes #843 — The two 3.86:1 contrast pairings (inactive Request tabs, pending onboarding step circles) moved to `slate-600` for WCAG AA.
- Fixes #843 — The parent header wordmark hides below 360px so the new Profile control does not overflow at 320px.
- Payable gating, checkout, and past-due badging were left untouched per the 2026-09-21 triage; no past-due badge was added.

## Deploy notes
No migrations. Pure frontend UI/component changes (nav, header, button styles, pause-enrollment form relocation, color tokens); no schema, API, or config changes. Safe to deploy independently.

## Risk / rollback
Low risk: changes are scoped to the parent shell (nav, header, payments/children pages, avatar/progress/calendar color tokens) and verified against the full gate (pytest, ruff, lint-imports, mypy-baseline, typecheck, eslint, build). Rollback is a revert of this PR.
