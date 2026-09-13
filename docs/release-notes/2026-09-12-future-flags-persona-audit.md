# Park student login and owner rollup; commit the persona lifecycle audit

## What changed

- Adds `TODO(#779)` markers on `frontend/app/(student)/layout.tsx`, `frontend/app/(owner)/owner/page.tsx` and the `ENABLE_OWNER_ROLE` / `ENABLE_STUDENT_LOGIN` flags in `backend/fly.toml`. Both features are parked future enhancements per the owner's 2026-09-12 decision; the code stays behind flags that remain `false` in production. Comment-only, no behaviour change.
- Commits `docs/reviews/2026-09-12-ui-persona-lifecycle-audit.md`, the audit that produced the `batch-3b` lifecycle/CRM/communications track (#772 to #778).

## Deploy notes

- No migrations, no environment changes. `fly.toml` gains a comment line only.

## Risk / rollback

- None: comments and a docs file. Rollback is a revert.

PR: #780
