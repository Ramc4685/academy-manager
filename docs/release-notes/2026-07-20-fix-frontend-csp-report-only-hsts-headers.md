# fix-frontend-csp-report-only-hsts-headers

PR: #315

## What changed
Added a `Content-Security-Policy-Report-Only` header (audit item QW5) covering all routes except the proxied Firebase auth helper (`/__/auth/*`), plus `Strict-Transport-Security` (1 year, includeSubDomains, no preload yet). The CSP allows only same-origin scripts/styles (plus the zone-injected Cloudflare Web Analytics beacon), Firebase identity/storage endpoints in connect-src/img-src, Cloudflare Insights RUM in connect-src, and Stripe hosted Checkout in form-action.

## Deploy notes
Header rollout is **report-only** initially — nothing is blocked. After deploy, watch browser DevTools consoles and `/api/csp-report` server logs (staging + prod) for CSP violations across login (email + Google popup/redirect), parent checkout redirect, and PWA install/update for a few days. Once clean, a follow-up PR flips the header name to `Content-Security-Policy` to enforce.

## Risk / rollback
Report-only means an over-tight policy is observational, not breaking. Rollback = revert this config-only change and redeploy.
