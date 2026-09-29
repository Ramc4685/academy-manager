# Host-trust settings required only when multi-academy is on

PR: #999

## What changed

- The production boot guard from #988 refused `saas_mode` without `platform_base_domain` and `proxy_shared_secret`. It now applies only when `tenancy_mode` is `multi_academy`.
- In `single_academy` mode the middleware refuses every academy except the primary, so the request host cannot select a tenant.
- This unblocks the production deploy of main, which failed on today's prod config (`single_academy`, `V2_SAAS_MODE` set, neither host-trust setting). A new test pins that config.

## Deploy notes

- No migration and no env or secret change.
- Before switching on multi-academy, set `V2_PLATFORM_BASE_DOMAIN` and `V2_PROXY_SHARED_SECRET`; boot still refuses without them.

## Risk / rollback

- Low. No runtime behaviour change, and multi-academy mode keeps the full guard.
- Rollback: revert this PR's merge commit.
