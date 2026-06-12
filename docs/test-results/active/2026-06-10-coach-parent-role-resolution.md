# coach parent role resolution

## Current State

Status: active

## Problem

Investigate whether a user with both coach and parent relationships should see coach or parent UI, and whether separate emails are required.

## Changed Files

- None recorded yet.

## Log

- 2026-06-10T15:56:22 main/NA: Task ledger created.
- 2026-06-10T15:58:03 main/working: Investigated role resolution. Frontend routes to coach before parent when /me returns both roles. Backend /me uses AuthClaims roles from users.roles in current non-SaaS production config. Session coach assignment alone does not grant coach persona access. Admin role change currently replaces roles with a single value instead of supporting dual parent+coach assignment.
## Verification

- No verification recorded yet.
- 2026-06-10T15:58:03: Static code trace only: inspected frontend/lib/api/me.ts, frontend/app/post-login/page.tsx, frontend/lib/auth/use-persona-auth.ts, backend/v2/interfaces/me_routes.py, backend/v2/shared/auth/middleware.py, backend/v2/contexts/identity/application/use_cases/load_auth_claims.py, backend/v2/contexts/identity/infrastructure/mongo_user_repo.py, backend/fly.toml. No runtime tests run because no code/data change was made.
## Reusable Lessons

- None recorded yet.
