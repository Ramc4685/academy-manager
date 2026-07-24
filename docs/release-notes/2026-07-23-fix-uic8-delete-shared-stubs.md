# fix-uic8-delete-shared-stubs

PR: #327

## What changed
`/calendar` and `/messages` now jump straight to your workspace. Both
routes were shell pages whose entire function was a single "open your
workspace" link; they're now minimal client redirects that fetch the
current user and forward immediately: `/calendar` → `/admin/sessions` |
`/coach/sessions` | `/parent/dashboard` | `/login` (by role), `/messages`
→ `/admin/messages` (admin) | `/post-login` (everyone else). The role
dispatch logic is unchanged — only the interstitial link card and the
ad-hoc `["me","calendar"]` / `["me","messages"]` query keys were dropped.
The URLs stay live as stable entry points for UIM13's real shared
Messages/Calendar screens later. Audit item UIC8.

## Deploy notes
none — frontend-only, no backend/API/env changes. No inbound links to
these routes exist in the app (verified by grep); only typed URLs or
stale bookmarks are affected, and they now skip a click instead of
landing on a dead-end card.

## Risk / rollback
Near-zero: same role→destination mapping as before, just applied
immediately instead of behind a click. Rollback = revert the single PR.

## Verification
`pnpm typecheck` and `pnpm lint` are clean (0 errors). `pnpm e2e` could
not get a clean full-suite run on this machine: multiple other worktree
sessions were concurrently running their own dev servers and Playwright
browsers, causing widespread 30s page-load timeouts across specs
unrelated to this change (chromium-mobile and webkit-mobile alike).
Confirmed this is environmental, not a regression: re-ran a failing spec
against the original (unmodified) stub pages via `git stash` and it
failed identically. No existing e2e spec visits `/calendar` or
`/messages` (verified by grep in the plan and again here), so this diff
has zero test coverage overlap either way. Recommend a clean e2e re-run
once the machine is less contended, but the diff itself is exercised and
correct per manual reasoning and the typecheck/lint pass.
