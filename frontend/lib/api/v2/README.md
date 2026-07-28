# lib/api/v2

Focused v2-only typed clients for newer frontend contracts.

All requests flow through `apiFetch` from `lib/api/client.ts`, which targets
`NEXT_PUBLIC_API_BASE` (defaults to `/api/v2`). No legacy `/api/*` calls
must originate from SaaS pages.

## Active academy

The active academy is selected by the user via the tenant switcher
(`components/admin/tenant-switcher.tsx`) and persisted in `localStorage`
under `am.activeAcademy`. The selection is read from `TenantContext` and
sent on every v2 request as the `X-Academy-Id` header by `apiFetch`. In
production the tenant is resolved from the host/subdomain per ADR-0007;
this header is honored only when the request comes from an
`allowed_internal_tenant_header` origin. For local development and admin
multi-academy switching it is the simplest path.

## Current clients

- `payroll.ts` calls admin monthly payroll endpoints under `/admin/payroll/*`.
- `payouts.ts` calls admin payout-period endpoints under `/admin/payout-periods/*`.
- `sessions.ts` calls admin session and occurrence endpoints.
- `students.ts` calls admin student progress and placement endpoints.
- `session-types.ts` calls the admin session-type billing catalog endpoints
  under `/admin/session-types/*`. Note `GET` returns active types only, so
  archiving (`DELETE`, a soft delete) is not reversible through this client.
- `memberships.ts` is the one deliberate fallback: `/me/memberships` is not
  exposed yet, so it derives a single active academy from `/me` until the real
  BFF route lands.
