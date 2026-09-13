# batch-5-shared-layout-polish

PR: #0

## What changed

- Addresses #451 (DS6 items b and e; item a — the admin nav regroup — is intentionally left for a follow-up PR, so #451 stays open) — the `(shared)` layout's role-check skeleton previously only covered the initial auth-pending state. Once it rendered `<main>` for a signed-in user, `/messages` and `/calendar` each flashed a bare "Redirecting..." string in `text-neutral-500` — a color outside the Rally palette — while their own `getCurrentUser` role lookup resolved, reproducing the same login-flash symptom #451 set out to remove on two routes it names by hand.
- The pending-state skeleton and its surface class now live in a single shared `components/shared/shell-skeleton` component, reused by all three pending branches (the outer layout, `/calendar`, `/messages`), so no branch can drift back to bare loading text.
- The PWA manifest and viewport `themeColor` used `#0a0a0a`, which matches no Rally design token; both now use `rally-paper` (`#f8fafc`) and `rally-ink` (`#0f172a`) so the install splash and browser chrome match the app's palette.
- Added `frontend/lib/app-chrome-colors.node-test.mjs`, a node test asserting the no-bare-loading-text rule holds across the shared layout and both pages (not just the layout in isolation), and that the manifest/viewport colors are Rally tokens.

## Deploy notes

No migrations. Frontend-only change (layout, two page components, a new shared skeleton component, the PWA manifest, and a node test) — no backend or schema impact, no manual deploy step.

## Risk / rollback

Low risk: the change only touches the pending/loading branches of three routes and two static color constants in the PWA manifest — no change to auth logic, redirect targets, or role checks themselves. Covered by the new node test asserting the skeleton is used consistently and the colors are on-palette. If this regresses in prod, revert this PR's merge commit.
