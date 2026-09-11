# hold-return-from-roster

PR: #PENDING

## What changed

Makes Return-from-hold reachable. #717 brought held students back onto the admin class roster, but a held row's menu still offered only Transfer, Drop and Delete, so an admin could see the held child and had no way to bring them back. This adds the Hold and Return actions, two API client calls against the hold endpoints that already shipped with #697, a shared Hold/Return dialog pair, and wires both into the class roster and the student profile's Sessions panel. An active row gains Hold; a held row gains Return. Every other status keeps the menu it already had, and no existing action was removed, so Pause and Resume are untouched.

## Deploy notes

Frontend only. No migration, no new env vars, no backend change: `POST /admin/enrollments/{id}/hold` and `/return` have been live since #697 and were simply unreachable from the UI.

## Risk / rollback

Two menus gain one entry each on two admin screens; nothing is removed or re-gated. Family notification on hold and return is deliberately not included and remains a separate task, so holding or returning a child still sends no email. `reclaim_pending` rows are intentionally left alone: they chip as ON HOLD like `held` but offer no Return, because nothing here establishes what Return means mid-reclaim. Typecheck, 329 unit tests and lint all pass. Revert the merge commit if this regresses.
