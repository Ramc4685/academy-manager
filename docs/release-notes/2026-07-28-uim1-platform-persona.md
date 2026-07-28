# uim1-platform-persona

PR: #377

## What changed
Ships the first slice of the platform-operator surface (UIM1 Phase 1), which
previously had zero UI despite roughly 35 backend routes — tenant onboarding
and lifecycle were reachable only via curl. Adds a new `(platform)` route
group guarded on `platform_roles` (tenant admins cannot reach it), with a
tenant list (create + bootstrap academy) and a tenant detail page exposing
status/health, lifecycle actions (activate/suspend/cancel/reactivate, the
destructive ones behind a reason dialog), and a plan/limits editor. Backed by
a new `GET /platform/tenants` route readable by `platform_admin` and
`platform_support`. Mutation controls are hidden for the support tier; the
server independently returns 404 for support writes, so client-side gating is
cosmetic only. `CurrentUser` now carries `platform_roles`, which the frontend
had never modelled.

## Deploy notes
None — no migrations, no new env vars. `enable_platform_routes` already
defaults to true, and `_validate_launch_settings` still refuses to boot when
`env=prod` AND `tenancy_mode=single_academy` AND the flag is on; that
behaviour is unchanged. This UI is effectively dark-launched behind the
frontend guard, so enabling it in production still requires either
`tenancy_mode=multi_academy` or a separate platform-ops deployment.

## Risk / rollback
Low risk and additive. Every `/platform/*` route 404s (not 403s) for
non-platform callers, so the surface stays invisible to tenant users even if
the client guard were bypassed. One notable hardening: the Mongo tenant list
skips legacy `academies` documents that fail `Tenant` validation — many
predate the platform context and lack `primary_domain` — and logs a warning,
so a single malformed row cannot 500 the whole operator list. Rollback:
revert this PR; the `(platform)` directory and its manifest entries delete
cleanly and the backend list route becomes unused.

Known gap: these routes are not covered by the local-auth e2e inventory
sweep, which seeds only admin/coach/parent users and has no platform operator
to sign in as. The `platform` role is excluded from that sweep the way
`proxy` already is.

Verified: backend `v2/tests` (2593 tests) green and `ruff check v2` clean;
frontend `pnpm typecheck` and `pnpm lint` clean; full
`scripts/dev/pre-push-checks.sh` green end-to-end including `pnpm e2e`.
