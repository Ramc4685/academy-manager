# auth-request-caching

PR: #584

## What changed
Every authenticated request paid a synchronous Firebase HTTPS round trip
(`verify_id_token(..., check_revoked=True)`) plus 4-6 uncached Mongo
lookups for tenant routing, tenant health, and claims building (`#527`).
Three short-TTL in-process caches now sit on that hot path:
`FirebaseTokenVerifier` memoizes successful token verifications for 60s
keyed by SHA-256 of the raw token (capped at the token's own `exp`,
failures never cached), `CachingAcademyLookup` caches positive
slug/domain -> academy_id routing hits for 60s (misses never cached, so
new tenants route immediately), and the tenant-servability checker
caches `get_tenant_health` per academy for 30s. A new bounded `TTLCache`
primitive lives in `backend/v2/shared/caching.py`; 11 unit tests pin the
caching semantics.

## Deploy notes
No configuration, migrations, or index changes. Caches are per-process
and empty at boot, so the first request per token/tenant behaves exactly
as before. Multi-instance deployments each warm their own cache.

## Risk / rollback
Firebase-side revocation (`revoke_refresh_tokens`) or user disablement
can lag up to 60s for a token verified within the window, and a tenant
suspension can take up to 30s to gate requests — immediate lockout still
works per request through `users.is_active` and membership status in
`LoadAuthClaims`, which are the levers admin tooling actually uses.
Rollback is a plain revert: no persisted state is involved, and the
pre-cache behavior returns on the next deploy.
