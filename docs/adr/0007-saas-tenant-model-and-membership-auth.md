# ADR-0007: SaaS Tenant Model And Membership-Based Auth

**Status:** Accepted
**Date:** 2026-05-21
**Deciders:** RamC (architect)
**Supersedes:** Extends ADR-0006 (which established tenant-ready, single-tenant shipped)
**Ticket:** P0-07

## Context

ADR-0006 established a tenant-ready architecture: every v2 collection has `academy_id` as the leading index field, all v2 repositories extend `TenantScopedRepository`, and shipping one tenant was the right call. That decision deliberately deferred multi-tenancy to a config flip.

The product is now ready to make that flip — but the architecture assessment (`docs/requirements/2026-05-21-saas-data-model-architecture-assessment.md`) identified that the current model is **tenant-aware, not SaaS-complete**. Three structural gaps block safe multi-tenancy:

1. **Identity is single-tenant shaped.** `users.academy_id` and `users.roles` embed academy context inside the user record. A parent with children at two academies, a coach working for multiple academies, or a platform admin cannot be represented correctly.

2. **Tenant resolution relies on a default.** Auth middleware reads `settings.default_academy_id`. In SaaS mode every request must resolve the academy explicitly from the domain or subdomain — not from a configured fallback.

3. **Legacy `/api/*` routes are not tenant-safe.** Many legacy handlers perform raw Mongo reads without `academy_id` filters. These routes were written as single-tenant code and must not be reachable in SaaS mode.

Because there is no production data to migrate, the architecture stance shifts from "migrate carefully" to "build clean." SaaS is v2-only from the start.

## Decision

**SaaS mode is v2-only. Identity is separated into global users and per-academy memberships. Tenant is resolved explicitly from the request domain or subdomain, never inferred from user alone. Legacy routes are forbidden in SaaS mode.**

Specifically:

### 1. SaaS is v2-only

- All SaaS traffic uses `/api/v2/*` routes exclusively.
- Legacy `/api/*` routes are forbidden in SaaS mode. Requests that match legacy route paths are rejected with `410 Gone` before any legacy handler executes.
- No new frontend code calls legacy routes.
- No SaaS workflow depends on legacy behavior.
- Any exception requires explicit architecture approval and a new ADR amendment.

### 2. Database-per-tenant is rejected for now

- Shared MongoDB with `academy_id` scoping continues (per ADR-0006).
- Operational complexity of per-tenant databases (migrations across N DBs, connection pooling, per-tenant dump/restore) is not justified at current scale.
- `TenantScopedRepository` remains the isolation boundary.
- Revisit via fresh ADR if regulatory isolation requirements emerge or tenant count demands physical separation.

### 3. Global identity with per-academy memberships

Split identity from academy membership:

```
users
- user_id
- firebase_uid
- email
- normalized_email
- display_name
- phone
- global_status
- created_at
- updated_at

academy_memberships
- membership_id
- academy_id
- user_id
- roles              # roles within this academy only
- status
- invited_by
- invited_at
- accepted_at
- created_at
- updated_at

platform_roles
- platform_role_id
- user_id
- role              # e.g. PLATFORM_ADMIN, PLATFORM_SUPPORT
- status
- granted_by
- granted_at
```

Indexes:

```
users:
- unique(firebase_uid)
- unique(normalized_email)

academy_memberships:
- unique(academy_id, user_id)
- index(user_id, status)
- index(academy_id, roles, status)

platform_roles:
- unique(user_id, role)
```

`AuthClaims` carry:

```
user_id
academy_id
membership_id
roles_for_this_academy
platform_roles
```

Roles are academy-specific. Platform admin access is carried in `platform_roles` and checked separately from academy role guards.

### 4. Explicit tenant resolution order

Tenant is resolved per request in this order:

1. **Subdomain** — `{slug}.app.example.com` maps to academy slug.
2. **Custom domain** — verified custom domain from `academy_domains` collection maps to academy.
3. **Approved internal header** — a named internal header accepted only for internal jobs and platform admin tooling. This header is disabled in SaaS production mode unless explicitly configured via `allowed_internal_tenant_header` in settings.

After resolving the academy:

4. Validate that the authenticated user has an active `academy_membership` for that academy.
5. Set `request.state.auth_claims` including `academy_id`, `membership_id`, and academy roles.
6. Reject requests where membership is missing or inactive.

No request may infer tenant from user alone. `default_academy_id` must not appear in SaaS request paths.

### 5. No `default_academy_id` in SaaS request paths

`settings.default_academy_id` is retained for local development and non-SaaS single-tenant compatibility only.

In SaaS mode (`settings.saas_mode = True`), any code path that would fall back to `default_academy_id` must instead raise or return an auth error. Composition helpers that currently inject `settings.default_academy_id` must be refactored to consume `request.state.auth_claims.academy_id`.

## Enforcement

These mechanisms make the decision durable:

1. **SaaS mode flag.** `settings.saas_mode: bool` enables all SaaS enforcement. Disabled by default; enabled by env in SaaS deployments.
2. **Route middleware.** In SaaS mode, incoming requests matching `/api/*` (legacy prefix) are intercepted before routing and rejected `410 Gone`.
3. **Tenant resolver.** A dedicated `shared/tenancy/resolver.py` resolves academy from domain/subdomain. Resolver raises if academy is unknown or membership is absent.
4. **No `default_academy_id` in SaaS.** Any usage of `settings.default_academy_id` in SaaS-mode code paths fails a CI lint rule.
5. **Membership validation in auth middleware.** Auth middleware calls the membership repository after token verification. Missing membership raises `403 Forbidden`.
6. **Tenant isolation tests.** Every tenant-owned repository must have at least one cross-tenant read rejection test (from ADR-0006; expanded to include membership and resolution tests).

## Options Considered

### Option A: SaaS v2-only with membership-based auth (chosen)

**Pros:**
- No production data migration required.
- Membership model correctly handles multi-academy users (parent at two academies, coach working multiple locations, platform admin).
- Explicit domain resolution removes any risk of tenant confusion.
- Legacy route ban is a clear safety boundary.

**Cons:**
- Requires refactoring `users` identity model and auth claims.
- Requires updating all composition helpers that inject `default_academy_id`.
- Domain/subdomain infrastructure must be built.

### Option B: Keep current model, just add a second academy

**Pros:** No identity refactor.

**Cons:**
- One user = one academy. Second academy for existing users is impossible without schema surgery at scale.
- `default_academy_id` fallback would cause tenant confusion under concurrent requests.
- Legacy route exposure would allow cross-tenant data leakage.
- Rejected — unsafe for multi-tenancy.

### Option C: Database-per-tenant

**Pros:** Physical isolation. Easy data export per tenant.

**Cons:**
- Mongo-DB-per-tenant multiplies connection management complexity.
- Migrations must run across N databases.
- Not justified at current scale.
- Rejected. Reconsider if regulatory or scale requirements change.

### Option D: Retrofit legacy routes for SaaS

**Pros:** Reuses existing code.

**Cons:**
- Legacy handlers perform dozens of raw Mongo reads/writes without `academy_id`. Auditing and patching all of them is error-prone and high-risk.
- Any missed path is a data-leak vulnerability.
- Cost-benefit is strongly negative compared to the v2-only stance.
- Rejected — the clean break is the safe choice.

## Consequences

**Becomes easier:**
- A user can belong to multiple academies with different roles. Zero schema work per new membership.
- Tenant resolution is deterministic and auditable.
- Legacy route exposure to SaaS tenants is structurally impossible.
- Platform admin tooling can be built on `platform_roles` without touching academy auth.

**Becomes harder:**
- All frontend calls must use v2 endpoints. Any legacy call from a SaaS page is a bug.
- Auth claims now carry `membership_id`. Consumers that only expected `academy_id` and `roles` must be updated.
- Domain/subdomain routing infrastructure must be provisioned (DNS wildcards, `academy_domains` collection, verified domain flow).

**To revisit:**
- If a user needs cross-tenant views within a single request (e.g., a parent switching academies in-session), the `ContextVar` model in `shared/tenancy/` requires a new ADR.
- If scale or compliance demands physical isolation, revisit database-per-tenant via a fresh ADR.

## Downstream ADRs and Tasks Required

This ADR creates the following mandatory follow-on work (see `docs/plans/2026-05-21-saas-v2-parallel-execution-plan.md`):

| Task | Description |
| --- | --- |
| 0.2 | Add `saas_mode` config flag; guard `default_academy_id` in SaaS paths |
| 0.3 | Enforce v2-only routing; reject legacy routes in SaaS mode |
| 1.1 | Add `User`, `AcademyMembership`, `PlatformRole` domain models |
| 1.2 | Add Mongo repositories and indexes for membership collections |
| 1.3 | Implement tenant resolution middleware |
| 1.4 | Implement tenant bootstrap use case |
| 2.1 | Tenant isolation test harness |
| 2.2 | Static raw Mongo guard |

## Action Items

1. [ ] Implement `saas_mode` flag in `backend/v2/shared/config/settings.py` (Task 0.2).
2. [ ] Add legacy route rejection middleware activated by `saas_mode` (Task 0.3).
3. [ ] Add `academy_memberships` and `platform_roles` collections and domain models (Task 1.1, 1.2).
4. [ ] Refactor `AuthClaims` to include `membership_id` and academy-scoped roles (Task 1.1).
5. [ ] Implement `shared/tenancy/resolver.py` with subdomain → custom domain → internal header resolution order (Task 1.3).
6. [ ] Remove `default_academy_id` from all SaaS request paths; add CI lint rule (Task 1.3).
7. [ ] Write tenant-isolation tests covering membership validation and domain resolution rejection (Task 2.1).
