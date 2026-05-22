# lib/api/v2

v2-only typed clients for SaaS Wave 5 admin frontend.

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

## Stable vs. mocked endpoints

Backend Waves 1-4 have shipped contracts for:

- identity / memberships  (used by `memberships.ts`)
- session occurrences      (used by `sessions.ts`)
- billing ledger/invoices  (used by `billing.ts`)
- waiver signatures        (used by `waivers.ts`)
- message campaigns        (used by `campaigns.ts`)

Wave 5 Agent A is still finishing reporting read models + payout
persistence. Files under `mock.ts` and entries marked `// TODO(wave5-A)`
inside other clients route to a clearly-labelled local fake until Agent
A's endpoints merge.
