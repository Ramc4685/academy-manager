# console error service worker and admin 500 fixes

## Current State

Status: active

## Problem

Console shows service-worker no-response noise plus 500s for admin dashboard attention and Stripe Connect onboarding link

## Changed Files

- None recorded yet.

## Log

- 2026-07-04T09:14:33 main/NA: Task ledger created.
- 2026-07-04T09:14:41 main/working: Investigated console errors. Planned focused fixes for dashboard attention partial failure, Stripe Connect onboarding provider-error mapping, and service-worker no-response handling.
- 2026-07-04T09:18:20 main/working: Implemented dashboard attention partial-failure handling, sanitized Stripe Connect onboarding provider errors, service-worker quiet handling for blocked Cloudflare beacon/auth helper failures, and focused regression tests.
- 2026-07-04T09:18:55 main/review: Manual security review using .claude/agents/security-reviewer.md plus VibeSec checklist: no findings. Auth/persona guards unchanged, tenant_scope remains around Connect account repo calls, redirect allowlist remains before Stripe calls, provider errors are sanitized, no secrets logged or committed. security-reviewer subagent was not spawned because this session's subagent tool policy requires explicit user request.
## Verification

- No verification recorded yet.
- 2026-07-04T09:18:20: Focused pytest: 9 passed for dashboard attention, admin connect-link, and Connect onboarding failure mapping. Broader touched backend files: 23 passed. Ruff check/format on touched backend files passed. Frontend pnpm typecheck passed with /opt/homebrew/bin on PATH. Frontend pnpm build passed and bundled service worker; existing unused eslint-disable warnings only.
## Reusable Lessons

- None recorded yet.
