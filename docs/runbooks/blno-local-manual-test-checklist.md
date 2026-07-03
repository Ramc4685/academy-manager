# BLNO local manual test checklist

Use this checklist for local Docker SaaS-mode manual testing of the seeded
BLNO-style academy data. It complements the automated smoke in
[saas-local-staging.md](saas-local-staging.md); it does not replace the smoke
or prove production readiness.

## Setup

1. Start the local stack from the project root:

   ```bash
   scripts/dev/saas_staging.sh up
   scripts/dev/saas_staging.sh blno-seed
   ```

2. Open the BLNO tenant frontend:

   ```text
   http://blno.localhost:3000/login
   ```

   Use `blno.localhost` for Docker SaaS manual testing. Tenant resolution is
   host-based, and `blno-academy.localhost` is not the canonical local BLNO
   route.

3. If the stack has stale data, reseed it:

   ```bash
   scripts/dev/saas_staging.sh blno-seed
   ```

4. Use Firebase Auth emulator credentials only. The SaaS staging emulator
   password file lives at `.local/saas-staging-credentials.json` when the
   SaaS staging seed is used. The BLNO local seed also prints local-only login
   credentials at the end of `scripts/local_test_stack.sh seed`; do not copy
   these into committed files.

## Persona Logins

| Persona | Local login | Password source |
| --- | --- | --- |
| Admin | `ramchand4685@gmail.com` | Local seed output; current known local seed password is `Admin@12345`. |
| Coach | `gowtham@blno.academy` or `kishore@blno.academy` | Local seed output; current known local seed password is `Coach@12345`. |
| Parent | Seeded BLNO parent email, for example `manojedward.btech@gmail.com` when present | Local seed output; current known local seed password is `Parent@12345`. |

If any login fails, inspect the Firebase Auth emulator UI at
`http://localhost:4000`, then rerun the seed before filing an app bug.

## Entry Checks

| Check | Expected result | Pass/fail notes |
| --- | --- | --- |
| Open `http://blno.localhost:3000` | Frontend loads without redirecting to an unknown tenant error. | |
| Admin login | Admin lands on the admin dashboard and `/api/v2/me` identifies admin membership for the BLNO tenant. | |
| Coach login | Coach lands on the coach experience and cannot open admin-only routes. | |
| Parent login | Parent lands on the parent experience and cannot open admin or coach-only routes. | |
| Refresh after login | Session persists through Firebase emulator auth; page remains tenant-scoped. | |

## Persona Checks

### Admin

| Check | Expected result | Pass/fail notes |
| --- | --- | --- |
| Admin dashboard opens | Shows operational summaries for the BLNO tenant, not a generic or cross-tenant state. | |
| Admin navigation | Dashboard, Sessions, Students, Coaches & Parents, Waitlist, Pause requests, Payments, Dues follow-up, Expenses, Coach payouts, Coach payslip, Reports, Messages, Waivers, Settings, and Audit logs are reachable or clearly unavailable. | |
| Tenant data | Visible students, sessions, invoices, and users belong to BLNO seed data only. | |
| Product feedback gaps | Known gaps from [the admin validation report](../requirements/2026-05-21-admin-product-validation-report.md) are not treated as pass criteria until implemented. | |

### Coach

| Check | Expected result | Pass/fail notes |
| --- | --- | --- |
| Coach home | Shows only sessions or attendance work assigned to the logged-in coach. | |
| Attendance flow | Attendance entry uses session occurrence data when available and does not require typing internal IDs. | |
| Coach access control | Direct navigation to `/admin` redirects or blocks. | |
| Substitute coverage | If substitute coaching is not implemented in the current app, record it as a known product gap rather than a failure of this checklist. | |

### Parent

| Check | Expected result | Pass/fail notes |
| --- | --- | --- |
| Parent home | Shows only the logged-in parent's children and account state. | |
| Payments | Parent-visible payment rows are readable and do not expose internal database IDs. | |
| Waivers | Parent can see required waiver status; signed-document access may remain a known gap until implemented. | |
| Parent access control | Direct navigation to `/admin` and `/coach` redirects or blocks. | |

## SaaS Safety Checks

| Check | How to test | Expected result | Pass/fail notes |
| --- | --- | --- | --- |
| Legacy `/api/*` blocked | Request a legacy endpoint such as `/api/health` while `V2_SAAS_MODE=true`. | Legacy route returns the SaaS guard response, not normal legacy data. | |
| Tenant host required | Open the frontend without a tenant host, such as bare `localhost`, when SaaS mode is active. | App does not silently infer BLNO from the user alone. | |
| Unknown tenant rejected | Open an unseeded host such as `http://unknown.localhost:3000`. | Unknown tenant is rejected before tenant-owned data renders. | |
| Cross-persona routes blocked | Try admin routes as coach and parent, coach routes as parent, and parent routes as coach. | Route guards redirect or deny access. | |
| No normal UI internal IDs after Wave 9 | Inspect admin, coach, and parent pages after Wave 9. | Normal UI hides Mongo IDs, Firebase UIDs, payout IDs, raw student IDs, and recipient IDs; support/audit-only views may still expose IDs intentionally. | |

## Admin Route Matrix

Run the route-level checks in
[saas-admin-route-matrix.md](saas-admin-route-matrix.md) after the entry and
persona checks pass.

## Handoff Notes

- This checklist is for local manual verification only.
- It does not certify production launch gates in
  [2026-05-22-saas-production-readiness.md](../requirements/2026-05-22-saas-production-readiness.md).
- Do not send real email, use real Stripe keys, or run destructive database
  operations during this checklist.
