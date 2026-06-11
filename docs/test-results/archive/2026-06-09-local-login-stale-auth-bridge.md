# local login stale auth bridge

## Current State

Status: active

## Problem

Local BLNO login can bounce back to /login after successful Firebase emulator sign-in because browser-stored auth bridge state can outlive emulator reseeds.

## Changed Files

- None recorded yet.

## Log

- 2026-06-09T08:09:07 main/NA: Task ledger created.
- 2026-06-09T08:10:56 main/working: Added auth bridge cookie helper, clearing stale bridge state on login/post-login, and forcing fresh Firebase token before /me.
## Verification

- No verification recorded yet.
- 2026-06-09T08:14:43: Red test first failed with missing auth-bridge-cookie.ts; after implementation, node --no-warnings --test lib/api/auth-bridge-cookie.node-test.mjs passed (2 tests).
- 2026-06-09T08:14:43: pnpm typecheck passed.
- 2026-06-09T08:14:46: pnpm lint passed. Manual in-app browser verification at http://blno.localhost:3001/login with seeded admin reached /admin dashboard after restarting only the frontend dev process.
## Reusable Lessons

- None recorded yet.
