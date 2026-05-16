# ADR-0006: Tenant-ready, single-tenant shipped

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** RamC (architect)
**Ticket:** P0-06

## Context

The plan describes the product as "academy management" — a multi-tenant SaaS shape — but today it serves a single academy. The architect review caught a contradiction: claiming multi-tenancy as the product shape while shipping single-tenant code creates a future migration risk (data, queries, auth claims, and security boundaries all need retrofit). The pragmatic answer is to *build the boundary now*, *ship one tenant today*, and *avoid running multi-tenant infrastructure prematurely*.

The cost of retrofitting tenant isolation later is enormous (every collection, every query, every test). The cost of building it from day one in v2 is small (~half a day per context) if it's enforced by infrastructure rather than convention.

## Decision

**Build the tenant boundary in v2 from day one. Ship single-tenant. Make turning on multi-tenancy a configuration change, not a code change.**

Specifically:

1. Every domain collection in v2 has `academy_id` as the leading field of every index and the leading filter of every query.
2. A `TenantScopedRepository` base class in `shared/tenancy/` injects `academy_id` from a `ContextVar` into every repository call. Application code does not handle `academy_id` directly.
3. `academy_id` is hard-coded in env (`DEFAULT_ACADEMY_ID`) for now. A single value. Auth claims carry it; auth middleware sets the `ContextVar`.
4. Multi-tenancy is a config flip later — change auth claim resolution to read tenant from the user record and remove the env default. **No schema migration needed.**

## Enforcement (load-bearing)

This rule is what makes the decision durable:

> **Application code never references `academy_id` directly.** Repositories carry it. The application layer (use cases, domain) has no knowledge of tenants — they operate on aggregates that are already scoped.

Enforcement mechanisms:

1. **`TenantScopedRepository` base class.** All Mongo repos in `*/infrastructure/` extend it. The base class reads `academy_id` from `shared/tenancy/context.py`'s `ContextVar`, injects it into every `find_*`, `update_*`, `delete_*`, and into every inserted document, and raises `TenantContextUnset` if missing.
2. **`import-linter` rule.** `academy_id` as a string literal or attribute access is forbidden outside `shared/tenancy/` and `*/infrastructure/`. Violations fail CI.
3. **Tenant-isolation test per repository.** Every Mongo repo must have a test asserting that a query under one `academy_id` returns nothing when documents exist only under another. Repos without this test fail a custom pytest check.
4. **Auth middleware sets the `ContextVar`** before any use case runs. The middleware is the single producer; downstream code is the consumer.

If a use case "needs" `academy_id`, it doesn't. It needs to call a repository that already has it.

## Options Considered

### Option A: Tenant-ready, single-tenant shipped (chosen)

**Pros:**
- Future migration to multi-tenant is a config flip + auth claim change. Schema, queries, tests, and indexes are already correct.
- Tenant-isolation tests catch leaks the moment they're introduced.
- Multi-tenant becomes a product decision, not an engineering project.

**Cons:**
- Half a day per context to wire correctly.
- Engineers must trust the base class — surprising at first.

### Option B: Single-tenant only, retrofit later

**Pros:** Slightly less code today.

**Cons:**
- Retrofitting tenant isolation requires touching every collection, every query, every test, every index. A multi-month project that we'd hit at the worst possible moment (when the second academy is signed).
- Rejected on Total Cost of Migration.

### Option C: Multi-tenant from day one (sell second academy soon)

**Pros:** Forces full multi-tenant correctness today.

**Cons:**
- No second academy committed. Building infra and customer-management UI for it would be speculative.
- Multi-tenant operational concerns (per-tenant rate limits, per-tenant Stripe accounts, per-tenant data exports) are real and unbounded — we'd be solving problems we can't yet shape.
- Rejected — too speculative.

### Option D: Database-per-tenant (Postgres schema-per-tenant or Mongo DB-per-tenant)

**Pros:** Strongest isolation. Easy data export per tenant.

**Cons:**
- More operational complexity (migrations across N databases).
- ADR-0001 keeps Mongo; Mongo-DB-per-tenant adds connection management complexity.
- Premature for our scale. Reconsider via fresh ADR if multi-tenant becomes real and scale demands physical isolation.

## What "tenant-ready" means concretely

For every collection touched in v2:

- The Mongo index has `academy_id` as the leading field (see plan §0.7 index table).
- The repo extends `TenantScopedRepository`.
- A tenant-isolation test exists.
- The aggregate (or query result) does **not** include `academy_id` in its public shape — it's an infra concern.

For auth:

- Firebase token verification produces an `AuthClaims` value object (Identity context, W1A-02) that includes `academy_id`.
- The auth middleware sets `shared/tenancy/context.py`'s `ContextVar` from claims and unsets it on response.
- Stripe webhook handlers, which arrive without a user token, derive `academy_id` from the payment record (which carries it) — handled in Wave 2 with a dedicated outbox path.

## Consequences

**Becomes easier:**
- Adding a second academy is "create a user with a new `academy_id` claim." Zero schema work.
- Per-tenant data export becomes a single query per collection.
- Future per-tenant features (custom branding, custom rates) are scoped via existing claims.

**Becomes harder:**
- Engineers must trust the repo base class. The first time someone tries to write `db.collection.find({"foo": "bar"})` directly and it fails the lint rule, they will be momentarily confused. Documentation in `shared/tenancy/README.md` and an example in ADR-0005 cover this.
- Stripe webhooks need a dedicated tenant-resolution path. Designed into Wave 2.

**To revisit:**
- If we ever sell to a customer with regulatory requirements demanding physical isolation, ADR-0004-equivalent for database-per-tenant is required.
- If `academy_id` ever needs to vary within a request (cross-tenant admin views), the `ContextVar` model is wrong and a new ADR is required.

## Action Items

1. [x] Reject retrofit-later, full-multi-tenant-today, and database-per-tenant options.
2. [ ] Implement `TenantScopedRepository` and `shared/tenancy/context.py` (P0-12).
3. [ ] Add `import-linter` rule banning `academy_id` outside `shared/tenancy/` and `*/infrastructure/` (P0-12).
4. [ ] Require tenant-isolation test per repo as a custom pytest check (P0-12).
5. [ ] Document the model in `backend/v2/shared/tenancy/README.md`.
6. [ ] Set `DEFAULT_ACADEMY_ID` in env config (P0-11).
