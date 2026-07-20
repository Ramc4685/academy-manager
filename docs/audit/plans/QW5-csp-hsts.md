# QW5 — Add CSP + HSTS headers
Status: TODO
Size: S · Depends on: none · Tracker: ../TRACKER.md

## Problem
`frontend/next.config.ts` `headers()` (lines 28-44) sets X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, COOP — but no `Content-Security-Policy` and no `Strict-Transport-Security`.

## Current behavior (verified)
- Firebase Auth uses the **modular JS SDK** (`frontend/lib/auth/firebase.ts`) — no third-party `<script>`; auth calls hit `identitytoolkit.googleapis.com` / `securetoken.googleapis.com` via fetch. The auth helper is **proxied same-origin**: `next.config.ts` rewrites `/__/auth/:path*` → `https://<project>.firebaseapp.com/__/auth/:path*` (popup/redirect helper loads its own scripts inside that document, not ours).
- Stripe: **hosted Checkout via full-page redirect** (`window.location.href = res.redirect_url` in `parent/payments/page.tsx:241-319`). No `@stripe/stripe-js`, no `loadStripe`, no embedded frame (grep verified). So no `js.stripe.com` in script-src and no frame-src needed.
- Serwist service worker (`public/sw.js`) — same-origin script.
- Deployed on Cloudflare via OpenNext (`frontend/wrangler.jsonc`); wrangler config sets no headers (verified), and there is no `public/_headers`. Check the Cloudflare dashboard for zone-level Transform Rules before assuming ours are the only headers.

## Implementation steps
1. Add to the `source: "/(.*)"` header block, Report-Only first:
   `Content-Security-Policy-Report-Only`: `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://firebasestorage.googleapis.com; font-src 'self' data:; connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://firebasestorage.googleapis.com <API origin from NEXT_PUBLIC_API_URL>; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://checkout.stripe.com; object-src 'none'`
   (`'unsafe-inline'` in script-src is required by Next.js inline bootstrap unless nonces are wired — accept for v1.)
2. Add `Strict-Transport-Security: max-age=31536000; includeSubDomains` (defer `preload` until confident all subdomains are HTTPS-only).
3. Exclude the `/__/auth/:path*` block from `frame-ancestors 'none'` (it already overrides X-Frame-Options to SAMEORIGIN — mirror that).
4. Bake for a few days in staging+prod watching DevTools console for CSP-Report-Only violations across login (email + Google popup/redirect), parent checkout redirect, PWA install/update.
5. Flip header name to `Content-Security-Policy` once clean.

## Verification
- `curl -sI https://<prod-host>/ | grep -i "content-security\|strict-transport"` shows both headers.
- Manual: login (both providers), parent payment → Stripe Checkout → return, image loads from firebasestorage, SW update — zero CSP violations in console.
- Playwright e2e suite green.

## Risks / rollback
- An over-tight CSP can break auth popups or the SW — Report-Only rollout (step 1/4) makes it observational until proven. Rollback = revert `next.config.ts` (config-only change, instant redeploy).

## PR checklist
- [ ] Release note if backend/ or frontend/ changed (per AGENTS.md)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
