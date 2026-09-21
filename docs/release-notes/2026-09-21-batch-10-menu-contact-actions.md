# batch-10-menu-contact-actions

PR: #0

## What changed

- Fixes #859 — Session detail now leads with the roster on a phone. Below `md`, Coaching staff, Class dates, and the Communication pack are collapsible sections (open by default) that render below the tab strip so the roster is the first thing an admin sees; the same content stays above the tabs on desktop. The layout choice is made in JS via the existing `useIsPhone` hook, so the DOM and tab order painted on each screen size actually match (no CSS-only reflow that would leave a phone screen reader hitting the desktop order first).
- Fixes #865 — Landed the first slice of "tappable contacts": phone numbers, WhatsApp links, and email addresses across admin people surfaces are now real `tel:`/`https://wa.me/`/`mailto:` links instead of plain text. Added a shared `telHref`/`whatsappHref`/`mailtoHref` helper module that returns `undefined` (never a dead/broken link) when a contact value is missing or unusable, plus a shared `ContactLinks` component and `contactMenuItems` row-menu entries, exported from the design system (`frontend/components/ds`) so every list can reuse the same behavior instead of re-implementing tap targets per page.

## Deploy notes

Frontend-only changes. No new migrations, no new environment variables, no backend schema or endpoint changes. Backend code is untouched by this branch.

## Risk / rollback

Low. Both changes are additive UI: a new collapsible-section layout driven by an existing hook, and a new shared contact-link helper/component consumed by existing pages. No data or schema impact. Full backend gate (pytest, ruff check/format, lint-imports, mypy-baseline) and frontend gate (tsc, eslint, `next build --webpack`) pass on the branch. To roll back, revert this PR's merge commit.
