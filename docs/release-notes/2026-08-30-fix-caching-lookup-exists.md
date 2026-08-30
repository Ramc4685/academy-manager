# caching-lookup-exists

PR: #587

## What changed
Two P2 fixes that were each correct in isolation broke each other on merge.
PR #571 (issue #519) added `exists()` to `AcademyLookupPort` so the internal
tenant header is honoured only when it names a registered academy; PR #584
(issue #527) wrapped that same port in `CachingAcademyLookup` to remove one to
two Mongo round trips per request. The wrapper implements only `find_by_slug`
and `find_by_domain`, so once both landed, `TenantResolver` called `exists()`
on an object that does not define it and every internal-tenant-header request
raised `AttributeError`, disabling that tenant source entirely.

`CachingAcademyLookup` now implements `exists()`, delegating to the wrapped
lookup under the module's existing positive-only cache policy: a hit is cached
for the 60-second TTL, a miss is never cached so a just-onboarded academy
passes the gate immediately rather than waiting out a stale negative.

## Deploy notes
None. No migration, no new environment configuration, no behaviour change for
slug or custom-domain routing. Deployments that do not use the internal tenant
header were unaffected by the defect and are unaffected by this fix.

## Risk / rollback
Revert the commit. Doing so restores the `AttributeError` on internal-header
requests, so prefer rolling back PR #571 or PR #584 instead if this needs to
be undone.
