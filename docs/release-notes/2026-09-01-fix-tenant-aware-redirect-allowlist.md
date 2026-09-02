# fix-tenant-aware-redirect-allowlist

PR: #628

## What changed
Stripe checkout/return URLs are now validated against the static configured
origins **plus the request's resolved tenant origins**, so a dynamically
onboarded academy can pay on its own host without an env-var edit.

Previously the allowlist came only from `CORS_ORIGINS` + `FRONTEND_URL`, while
tenants are resolved dynamically by subdomain or custom domain. A parent on
`https://blno-badminton.courtmastr.com` reached "Review & pay" and checkout
failed with `redirect url origin not allowed`; every newly onboarded academy hit
the same wall (admin Stripe Connect onboarding too).

The tenant origins are rebuilt from **stored records + server config**, never
from the request `Host`:

- New `backend/v2/shared/tenancy/origins.py` (`TenantOriginsResolver`) derives
  the academy's subdomain origin from its stored `slug` via the existing
  `academy_frontend_url`, plus one origin per `academy_domains` row with
  `status == "verified"`. Scheme and port come from `settings.frontend_url`, so
  an unauthenticated `x-forwarded-proto` cannot downgrade an origin to `http://`.
  Positive results are TTL-cached like the `#527` tenant-routing cache; a lookup
  failure returns `()` and degrades to today's static-only allowlist.
- `TenancyMiddleware` takes an optional `load_tenant_origins` port, stamps
  `request.state.tenant_origins`, and sets a new `current_tenant_origins()`
  ContextVar (returns `()` when unset — background jobs and non-SaaS deployments
  legitimately have none).
- `composition/parent.py::_validate_checkout_redirect_urls` and both
  `StartConnectOnboarding` wirings (`main.py`, `composition/admin.py`) now read
  static + tenant origins. `StartConnectOnboarding.allowed_redirect_origins`
  accepts a callable so the value is evaluated per call instead of frozen at
  construction.
- `validate_redirect_url` itself is unchanged — it stays a pure allowlist
  matcher, so the existing allowlist tests still guard the primitive.

Security note: the `Host` header may only select *which* academy, never what is
allowlisted. With `platform_base_domain` unset the resolver matches the first
Host label only, so `real-slug.attacker.example` resolves the real academy —
allowlisting that host verbatim would have created an open-redirect out of the
payment flow. Tests cover that case explicitly.

## Deploy notes
None. No migration and no new env var; existing `CORS_ORIGINS`/`FRONTEND_URL`
entries keep working unchanged. Per-tenant origins are active in SaaS mode only.

Known residual (pre-existing, deliberately not widened here): `find_by_domain`
resolves a tenant from an **unverified** `custom_domain` on the academy row,
while the origin builder reads verified `academy_domains` rows only. Such a host
still fails checkout exactly as it does today, now with an INFO log
(`checkout_redirect_rejected_without_tenant_origins`). Tightening
`find_by_domain` to require verification is a separate change with
tenant-resolution blast radius.

## Risk / rollback
Medium risk — this widens a security-critical allowlist. The widening is keyed
off the *resolved* `academy_id` and reads only stored, verified values, so a
tenant gains only its own already-public origins and tenant A can never
allowlist tenant B. Roll back by reverting this PR; checkout then reverts to
static origins only, which means any academy whose host is not in the Fly
`CORS_ORIGINS` secret cannot check out again.
