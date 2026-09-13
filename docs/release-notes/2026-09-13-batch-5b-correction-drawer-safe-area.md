# batch-5b: correction drawer safe-area padding

## What changed
- Fixes #746 — the payroll `CorrectionDrawer` is a full-height `inset-y-0` overlay; on the installed iOS PWA (viewport-fit=cover + translucent status bar) its header and Close button rendered underneath the status bar, where iOS swallows the first tap. Added `pt-[calc(1rem+env(safe-area-inset-top,0px))]` to the drawer header, matching the padding already used on the persona shell headers.
- Extended `shell-safe-area.test.ts` to enumerate every `inset-y-0` overlay under `app/` and assert it carries safe-area top padding, so a future overlay cannot ship unpadded without failing this test.

## Deploy notes
None. Frontend-only CSS/test change; no migrations, no environment variables, no backend changes.

## Risk / rollback
Low risk: the change is additive padding on one drawer header plus a new test. If an issue surfaces, revert this PR.

PR: #0
