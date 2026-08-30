# tenant-header-validation

PR: #571

## What changed
The internal tenant header (`V2_ALLOWED_INTERNAL_TENANT_HEADER`) was
trusted verbatim: `TenantResolver` returned the client-supplied value
directly as `academy_id` with no existence check and no shared secret,
and the header name was CORS-whitelisted so browsers could send it
cross-origin (`#519`). Any anonymous client that knew the header name
could tenant-resolve as an arbitrary or fabricated academy and seed
User/membership rows through public registration. The resolver now
honours the header only when the request also presents the proxy shared
secret via `x-cm-proxy-auth` (compared with `hmac.compare_digest`,
mirroring the rate limiter) AND the value names a registered academy
via the new `exists()` lookup on `AcademyLookupPort`; with no
`proxy_shared_secret` configured the header source is disabled entirely.
The header is no longer appended to CORS `allow_headers`. A related Host
weakness is closed behind the new `V2_PLATFORM_BASE_DOMAIN` setting:
when set, subdomain slug resolution only applies to hosts of the exact
form `<slug>.<platform_base_domain>`, so
`<victim-slug>.attacker.example` can no longer resolve the victim
tenant.

## Deploy notes
Deployments using the internal tenant header must now also set
`V2_PROXY_SHARED_SECRET` and send `x-cm-proxy-auth` on internal-job and
platform-tooling requests — the bare header stops resolving after this
deploy. Set `V2_PLATFORM_BASE_DOMAIN` (e.g. `app.example.com`) in SaaS
deployments to enforce base-domain matching; leaving it unset keeps the
legacy first-label behaviour. The edge should continue to strip the
internal header from external traffic. The in-repo SaaS staging stack is
self-consistent: `scripts/dev/saas_staging.sh` now generates
`V2_PROXY_SHARED_SECRET` into `.local/saas-staging.env` (backfilled into
existing env files), `docker-compose.saas.yml` sets
`V2_PLATFORM_BASE_DOMAIN=localhost`, and the readiness smoke presents
`x-cm-proxy-auth` via `PROXY_AUTH_VALUE`. Production (Fly) config must
be updated by an operator — see the deploy/ops follow-up comment on the
PR.

## Risk / rollback
Fail-closed by design: misconfigured internal jobs lose tenant
resolution (requests 4xx) rather than any tenant data being exposed.
Subdomain and custom-domain resolution for real tenants is unchanged
when `V2_PLATFORM_BASE_DOMAIN` is unset. Rollback is a revert of the
single PR; no migrations and no data changes are involved.
