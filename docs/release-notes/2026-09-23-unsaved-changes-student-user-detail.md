# Unsaved-changes guard on the student and user detail pages (UI-2)

PR: #TBD

## What changed

- Student detail: the Overview, Training and Family & Compliance edit forms and the Change parent picker now report unsaved edits to the admin shell's guard (#893). Switching student tabs (buttons, so the shell's link listener never saw them), any in-app link, and a reload or tab close now ask "Leave without saving?" instead of silently dropping the draft.
- User / staff detail: the profile form, the roles form, the coach pay-rate form and the coach session-assign picker do the same.
- A form is clean again as soon as a save succeeds or Reset is pressed; it does not wait for the refetch.
- Playwright: two new specs in `admin-shell.spec.ts` (stay keeps the typed value, confirm leaves, Escape returns focus to the tab).

## Deploy notes

None. Frontend only; no migration, no env vars.

## Risk / rollback

Low. Worst case is an extra confirm on a detail page. Roll back by reverting the PR.
