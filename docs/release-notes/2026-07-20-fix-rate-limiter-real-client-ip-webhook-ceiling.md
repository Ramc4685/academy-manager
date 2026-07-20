# fix-rate-limiter-real-client-ip-webhook-ceiling

PR: #312

## What changed
Audit item **C3**. The public-endpoint rate limiter (`backend/v2/shared/http/rate_limit.py`) previously keyed buckets on `request.client.host`, which behind Fly + the Cloudflare-hosted BFF proxy is the proxy hop — every real user shared one 20 req/60s bucket on registration/onboarding.

- **Tiered client-IP extraction**: `x-cm-proxy-auth` shared-secret match → trust `CF-Connecting-IP` (real end-client IP, forwarded unchanged by the BFF proxy); else `Fly-Client-IP` (Fly-stamped, unforgeable, correct for direct-to-Fly hits); else `request.client.host` (dev/tests). A direct client without the secret cannot rotate buckets by forging headers.
- **Stripe webhook ceiling**: `POST /api/v2/parent/webhooks/stripe` now has its own limit — 600 req/60s per client key (signature verification remains the auth; this only caps volumetric abuse).
- The BFF proxy (`frontend/lib/api/proxy-headers.ts`) strips any inbound `x-cm-proxy-auth` and attaches the server-held secret when configured.
- Middleware docstring now documents the single-machine constraint (process-local state; scaling Fly beyond one machine voids limits — shared-store limiter out of scope, GAPS.md #3).

## Deploy notes
**New env vars (optional, set both or neither):** generate one secret, then set
- `V2_PROXY_SHARED_SECRET` on the Fly backend app
- `BFF_PROXY_SHARED_SECRET` on the Cloudflare worker (server-side only — never `NEXT_PUBLIC_`)

Staging first, then prod. No migrations.

## Risk / rollback
- **Secret unset or misconfigured on either side**: tier 1 is skipped and keying degrades to `Fly-Client-IP` — worker-proxied users share the Cloudflare-egress bucket (exactly today's behavior, never worse). Watch 429 rates after deploy.
- **Webhook ceiling too low**: 600/min ≈ 10 events/sec sustained; Stripe retries with backoff on 429 and webhook processing is idempotent on event id, so no event loss. Raise the constant in `_PATH_LIMIT_OVERRIDES` if 429s appear in Stripe's dashboard.
- **Rollback**: revert the PR; the secret env vars are inert once the code no longer reads them.
