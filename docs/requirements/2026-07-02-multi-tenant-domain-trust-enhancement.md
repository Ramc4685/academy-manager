# Multi-Tenant Domain Trust and White-Label Readiness Enhancement

Date: 2026-07-02

## Problem

Production payment redirects currently rely on global backend origin configuration.
That works for a small single-academy setup, but it does not scale cleanly when each
academy is served on its own tenant domain.

The immediate production issue was:

```text
redirect url origin not allowed: 'https://blno-academy.courtmastr.com'
```

Root cause:

- Parent payment and billing portal flows build Stripe return URLs from the current
  browser origin.
- BLNO parents use `https://blno-academy.courtmastr.com`.
- Backend redirect validation only allowed the canonical global origin.

The short-term fix is to include BLNO's tenant host in production `CORS_ORIGINS`.
The long-term enhancement should make tenant domains first-class and avoid adding
every academy domain to global environment config.

## Product Direction

Use verified tenant domains as the source of truth for portal, auth, and payment
redirect trust.

Current BLNO domain remains:

```text
blno-academy.courtmastr.com
```

Recommended default for future tenants:

```text
{academy_slug}.courtmastr.com
```

Examples:

```text
smash.courtmastr.com
elite.courtmastr.com
austinbadminton.courtmastr.com
```

Future white-label domains should also be supported:

```text
portal.customer-domain.com
members.customer-domain.com
app.customer-domain.com
```

The naming style can vary by tenant, but the trust rule must not vary:

```text
Only verified domains belonging to the current academy may be used for auth and
Stripe return redirects.
```

## Non-Goals

- Do not use wildcard redirect trust such as `*.courtmastr.com` for Stripe returns.
- Do not use `CORS_ORIGINS=*`.
- Do not require renaming `blno-academy.courtmastr.com` immediately.
- Do not require custom white-label domains for every tenant.
- Do not allow one academy to redirect Stripe users to another academy's domain.

## Domain Model

Use `academy_domains` as the trusted domain registry.

Required fields:

- `domain_id`
- `academy_id`
- `domain`
- `domain_type`: `courtmastr_subdomain` or `custom`
- `status`: `pending`, `verified`, `failed`, `disabled`
- `is_primary`
- `purposes`: array containing any of `portal`, `auth`, `payments`
- `verification_method`: `managed_subdomain`, `dns_cname`, `dns_txt`, or `manual`
- `verification_token`, when needed
- `last_verified_at`
- `created_at`
- `updated_at`

Example:

```json
{
  "academy_id": "acad_blno_badminton",
  "domain": "blno-academy.courtmastr.com",
  "domain_type": "courtmastr_subdomain",
  "status": "verified",
  "is_primary": true,
  "purposes": ["portal", "auth", "payments"]
}
```

Future white-label example:

```json
{
  "academy_id": "acad_elite_racquets",
  "domain": "portal.eliteracquets.com",
  "domain_type": "custom",
  "status": "verified",
  "is_primary": true,
  "purposes": ["portal", "auth", "payments"]
}
```

## Backend Requirements

### R1. Tenant-Aware Redirect Validation

Payment redirect validation must allow:

- global canonical frontend origins, such as `https://academy.courtmastr.com`
- verified domains for the current `academy_id`

Payment redirect validation must reject:

- arbitrary external origins
- unverified tenant domains
- disabled tenant domains
- domains belonging to another academy
- wildcard-only matches

Affected flows:

- parent onboarding checkout
- parent autopay setup checkout
- invoice payment checkout
- balance payment checkout
- Stripe billing portal return URL

### R2. Shared Redirect Trust Service

Add a shared backend service/helper for trusted redirect origins.

Suggested location:

```text
backend/v2/shared/security/tenant_redirects.py
```

Responsibilities:

- parse origin from candidate redirect URL
- load verified domains for the current academy
- construct allowed origins from those domains
- include global configured frontend origins
- call existing strict `validate_redirect_url`
- expose one reusable method for payment flows

Expected shape:

```python
allowed_origins = await trusted_redirect_origins.for_academy(academy_id)
validate_redirect_url(url, allowed_origins=allowed_origins)
```

### R3. Do Not Trust All Tenant Domains Globally

The implementation must not validate against every row in `academy_domains`.
It must filter by the current `academy_id`.

This must be tested explicitly because it is the main tenant-isolation risk.

### R4. Prefer Backend-Generated Stripe URLs

As a follow-up hardening step, payment APIs should stop accepting full redirect URLs
from the frontend.

Preferred future contract:

```json
{
  "return_path": "/parent/payments",
  "flow": "invoice_payment"
}
```

Backend builds:

```text
https://blno-academy.courtmastr.com/parent/payments?invoice=paid
```

This should happen after tenant-aware redirect validation is in place.

### R5. Tenant Domain Administration API

Add or extend admin/platform APIs for domain management.

Suggested routes:

```text
GET    /api/v2/admin/academy/domains
POST   /api/v2/admin/academy/domains
PATCH  /api/v2/admin/academy/domains/{domain_id}
DELETE /api/v2/admin/academy/domains/{domain_id}
POST   /api/v2/admin/academy/domains/{domain_id}/verify
POST   /api/v2/admin/academy/domains/{domain_id}/make-primary
```

In future platform/owner mode, equivalent platform routes can manage domains across
all academies.

## Admin UI Requirements

Add a Domains panel under admin academy settings.

Suggested location:

```text
/admin/settings
```

Panel name:

```text
Domains
```

The UI should show:

- domain
- domain type
- status
- primary marker
- enabled purposes: portal, auth, payments
- last verification time
- setup warnings

Primary actions:

- Add domain
- Verify domain
- Make primary
- Disable/remove domain
- Copy DNS instructions
- Copy Firebase/OAuth instructions
- Run redirect trust check

For `courtmastr_subdomain` domains, the UI should make the managed setup clear:

```text
blno-academy.courtmastr.com
Status: Verified
Managed by CourtMastr
Used for: Portal, auth, payments
```

For custom domains, the UI should show DNS setup:

```text
portal.customer-domain.com
Status: Pending DNS
CNAME target: academy-next...
TXT verification: courtmastr-domain-verification=...
```

The UI should include an operational checklist per domain:

- Cloudflare route/DNS
- Firebase authorized domain
- Google OAuth redirect URI
- Backend redirect trust
- Stripe return URL check

## Acceptance Criteria

- BLNO remains supported on `https://blno-academy.courtmastr.com`.
- A new tenant can be added as `{slug}.courtmastr.com` without editing backend
  source or global `CORS_ORIGINS`.
- Stripe checkout and billing portal return URLs work on the tenant's verified
  primary domain.
- A tenant cannot use another tenant's domain as a Stripe return URL.
- Unverified custom domains are visible in Admin but cannot be used for payments.
- Admin settings shows domain status and setup actions.
- Production keeps exact CORS origins for credentialed requests.

## Test Plan

Backend unit tests:

- allows global canonical origin
- allows current academy verified domain
- rejects another academy's verified domain
- rejects current academy pending domain
- rejects random external domain
- rejects wrong scheme or port

Backend interface tests:

- invoice checkout accepts BLNO verified tenant origin
- balance checkout accepts BLNO verified tenant origin
- autopay checkout accepts BLNO verified tenant origin
- billing portal accepts BLNO verified tenant origin
- all payment flows reject cross-tenant domains

Frontend tests:

- Domains panel renders existing verified domain
- pending custom domain shows DNS instructions
- verification failure is visible
- primary domain action updates the UI
- payment redirect trust check result is visible

## Rollout Plan

1. Keep the current production CORS fix for BLNO.
2. Seed or verify `blno-academy.courtmastr.com` in `academy_domains`.
3. Add tenant-aware redirect validation behind focused tests.
4. Deploy backend with both old global origin support and new tenant-domain support.
5. Add Admin Domains panel.
6. Onboard the next tenant using `{slug}.courtmastr.com`.
7. Later, move Stripe flows to backend-generated return URLs.
8. Add custom white-label domain support when the first customer needs it.

## Operational Notes

Firebase and Google OAuth still require provider-side configuration for every served
auth domain. Domain onboarding should eventually automate or checklist these steps:

- Firebase Authorized domains
- Google OAuth Authorized JavaScript origins
- Google OAuth Authorized redirect URIs such as:

```text
https://{tenant-domain}/__/auth/handler
```

Stripe does not require pre-registering Checkout return URLs, but the application
must validate them before sending them to Stripe.

