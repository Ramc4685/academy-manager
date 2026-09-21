# batch-9-admin-people-payments-ui

PR: #0

## What changed

- Fixes #837 — Failed loads on admin dashboards no longer render as "all clear". A new pure helper `frontend/lib/ui/load-state.ts` (`statText`/`statHint`/`finiteText`) makes an unknown figure show a dash instead of a normalizer's zero, and a new design-system `ErrorNotice` component states the failure explicitly with a "Try again" button wired to the query's `refetch`.
- Fixes #840 — Added `frontend/lib/people-status.ts` as the single source of truth for the two People facts shown across admin pages: Login status (Not invited / Invited / Active, plus a No access state for switched-off user accounts) and Card status (No card / Card on file / Card declined). Includes chip variants and adapters for both backend registration spellings currently in use (billing-setup's `no_account`/`account_no_card`/`card_on_file` and family-billing's `not_invited`/`invited`/`registered`), so the two pages stop disagreeing on the same person.
- Fixes #839 — Students, Families and Users are now linked in both directions: the parent cell in the students list and the parent name in the student header link to `/admin/families/{parentId}`; the family header gains an "Account & login" link to `/admin/users/{parentId}`; a parent's user page gains a Family card linking back to the family with its student count. An admin can go from a student, to the family's money, to the parent's login in two clicks without having to remember names.
- Fixes #838 — Every high-impact admin action (the ones that previously used a native `window.confirm`) now asks a second time in the app's own confirmation dialog instead of a native browser prompt, matching the rest of the admin UI's styling and behavior.

## Deploy notes

Frontend-only change set. No new migrations, no backend API changes, and no environment variables to set.

## Risk / rollback

Low. All four fixes are additive UI/frontend changes (a new pure helper module, a new status-vocabulary module, new cross-links between existing pages, and swapping native `confirm()` calls for an in-app dialog component) with no data or schema impact. Full backend and frontend gates (pytest, ruff, mypy-baseline, tsc, eslint, next build) pass on the branch. To roll back, revert this PR's merge commit.
