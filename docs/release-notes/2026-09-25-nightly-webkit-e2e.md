# Nightly E2E WebKit green again: student header fits an iPhone, trial form spec waits for hydration

PR: #979

## What changed
- Admin student profile header (`/admin/students/[id]`): on a phone the actions menu now shares the name row, and the parent's contact links use the card's full width. At 390px (iPhone 14) the links used to sit beside the menu, which wrapped WhatsApp onto a third 44px row and pushed the tabs 28px below the fold. That broke #897's own "tabs visible without scrolling" acceptance check on webkit-mobile. From `sm` up the layout is one row, as before.
- `e2e/specs/public-tenant-trial-form.spec.ts` now waits for React to hydrate the server-rendered trial form before filling it. On webkit-mobile the first field was typed before hydration, the next render cleared it, and submit answered "Enter your name." instead of posting. No assertion was weakened, skipped or removed.
- These were the only failures in the Nightly E2E "Frontend E2E WebKit" job, which had failed on main since 2026-09-23. The geometry check (#905) and the trial form spec (#939) both landed after the last green nightly.

## Deploy notes
- Frontend only. No migration, no env vars, no backend change.

## Risk / rollback
- Low. The markup change affects one card on one admin page. The CSS moves from nested flex to a grid on phones, and the DOM content and test ids are unchanged. Chromium mobile/desktop and webkit-mobile runs of both specs pass.
- Rollback: revert this PR.
