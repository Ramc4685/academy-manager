# C3 — Rate limiter: real client IP + webhook coverage
Status: TODO
Size: S · Depends on: none · Tracker: ../TRACKER.md

## Problem

The public-endpoint rate limiter keys on the immediate TCP peer, not the end client. `backend/v2/shared/http/rate_limit.py:85-89`:

```python
@staticmethod
def _client_key(request: Request) -> str:
    if request.client is not None:
        return request.client.host
    return "unknown"
```

Uvicorn runs without `--proxy-headers` (`backend/Dockerfile:14`: `CMD ["uvicorn", "backend.v2.main:app", "--host", "0.0.0.0", "--port", "8001"]`), so behind Fly's proxy `request.client.host` is the Fly-internal hop. For traffic proxied through the Cloudflare-hosted Next.js worker, every real user additionally collapses onto the worker's egress — **all users share one bucket** on registration/onboarding: 20 requests/60s total (`rate_limit.py:28-29`) locks out legitimate signups, and an attacker consuming the shared bucket DoSes registration for everyone. Webhook ingest (`POST /api/v2/webhooks/stripe`, `backend/v2/interfaces/parent/webhook_routes.py:14-17`) has no limiter at all.

## Current behavior (verified)

- Wiring: `backend/v2/main.py:565` — `app.add_middleware(InMemoryRateLimitMiddleware)` with defaults (limit=20, window=60s, process-local dict).
- Limited paths (`rate_limit.py:15-18, 74-83`): `POST /api/v2/register/parent`, `POST /api/v2/parent/onboarding/start`, and `PATCH /api/v2/parent/onboarding/*` (except `/status`).
- **Which client-IP header survives end-to-end** (traced): the Next.js BFF proxy (`frontend/app/api/v2/[...path]/route.ts:21`) builds upstream headers via `buildProxyHeaders` (`frontend/lib/api/proxy-headers.ts:16-42`), which starts from `new Headers(requestHeaders)` — i.e. **copies all inbound headers** — and only deletes `host`, the identity header/cookie, and (on responses) hop-by-hop headers. Therefore `CF-Connecting-IP`, stamped by Cloudflare on the worker's inbound request, **is forwarded to the backend unchanged**. It survives end-to-end today; no proxy change is required, only backend extraction.
- `Fly-Client-IP` is stamped by Fly's edge with the TCP peer that connected to Fly: for worker-proxied traffic that is the Cloudflare egress (useless as a client key); for direct-to-Fly traffic it is the real client and cannot be spoofed by the client.
- Spoofing gap: a client connecting **directly** to the Fly hostname can send a forged `CF-Connecting-IP` header; trusting it unconditionally lets an attacker rotate fake IPs and evade limits entirely. A trusted-hop check is required.

## Proposed change

1. **Trusted-header client-IP extraction with a proxy shared secret.** Add `V2_PROXY_SHARED_SECRET` (optional). The Next.js proxy attaches `x-cm-proxy-auth: <secret>` to upstream requests. Backend key resolution, in order:
   1. If `x-cm-proxy-auth` matches the configured secret → trust `CF-Connecting-IP` (the real end-client IP Cloudflare stamped).
   2. Else → `Fly-Client-IP` (Fly-stamped, unforgeable, correct for direct hits).
   3. Else → `request.client.host` (local dev/tests), else `"unknown"`.
   When the secret is unset (dev/test), skip tier 1. This blocks header spoofing: a direct client without the secret gets keyed by its own Fly-Client-IP no matter what headers it forges.
2. **Webhook ingest limiting with a high ceiling.** Add `POST /api/v2/webhooks/stripe` as a second limiter class: 600 requests/60s per client key (Stripe retries in bursts; signature verification already rejects garbage, this only caps volumetric abuse). Implemented as a per-path limit override rather than a new middleware.
3. **Document the single-machine constraint** in the middleware docstring (state is process-local; scaling Fly beyond one machine silently voids limits — a shared-store limiter is out of scope here, per GAPS.md #3).

`--proxy-headers` on uvicorn is deliberately **not** part of the fix: it would only surface Fly's hop into `request.client`, and trusting `X-Forwarded-For` generically is weaker than the explicit Fly/CF headers above.

## Implementation steps

1. `backend/v2/shared/config/settings.py`: add `proxy_shared_secret: str | None = Field(default=None)` (env `V2_PROXY_SHARED_SECRET`; add the legacy-name fallback in `apply_legacy_deploy_fallbacks` following the pattern at :131-186 only if a non-V2 name is desired — recommend V2-only, no fallback).
2. `backend/v2/shared/http/rate_limit.py`:
   - Replace `_client_key` (:85-89) with an instance method implementing the tiered resolution above; constructor gains `proxy_shared_secret: str | None = None`. Use `hmac.compare_digest` for the secret comparison.
   - Add per-path limit overrides: extend the path table to `{(method, path): (limit, window)}`; add `("POST", "/api/v2/webhooks/stripe"): (600, 60)`. Keep the existing three parent paths at (20, 60).
   - Update the module/class docstring with the single-machine caveat.
3. `backend/v2/main.py:565`: pass the secret — `app.add_middleware(InMemoryRateLimitMiddleware, proxy_shared_secret=settings.proxy_shared_secret)`.
4. `frontend/lib/api/proxy-headers.ts`: in `buildProxyHeaders`, set `headers.set("x-cm-proxy-auth", process.env.BFF_PROXY_SHARED_SECRET)` when that env var is present (server-side only — never `NEXT_PUBLIC_`). Also `headers.delete("x-cm-proxy-auth")` from the inbound copy **before** setting, so a client cannot inject it.
5. Deploy config: generate one secret; set `V2_PROXY_SHARED_SECRET` on the Fly app and `BFF_PROXY_SHARED_SECRET` on the Cloudflare worker (staging first, then prod). Absent secret ⇒ tier-1 skipped ⇒ behavior degrades to Fly-Client-IP keying, never worse than today.

## Files to change

- `backend/v2/shared/http/rate_limit.py`
- `backend/v2/shared/config/settings.py`
- `backend/v2/main.py`
- `frontend/lib/api/proxy-headers.ts`
- `backend/v2/tests/unit/` (new/extended limiter tests; existing limiter tests live under v2/tests — locate with `grep -rl InMemoryRateLimit backend/v2/tests`)
- `frontend/lib/api/__tests__/` (proxy-headers unit test, alongside existing ones if present)

## Tests & verification

New backend unit tests (injected `clock` already supported, `rate_limit.py:31,37`):

- Key precedence: secret match + `CF-Connecting-IP` present → keys on CF IP; wrong/absent secret + forged `CF-Connecting-IP` → keys on `Fly-Client-IP`; neither header → `request.client.host`.
- Two distinct CF IPs through the trusted proxy get independent buckets (the shared-bucket regression).
- Forged `CF-Connecting-IP` without the secret does **not** rotate buckets.
- Webhook path: 600 allowed within the window, 601st → 429 with `Retry-After`; parent paths still cap at 20.

Frontend: unit test that `buildProxyHeaders` strips an inbound `x-cm-proxy-auth` and sets the server value when env present.

```bash
cd backend && pytest v2/tests -q && ruff check v2
cd frontend && pnpm test && pnpm typecheck
```

Staging check: from a shell, hit `POST /api/v2/register/parent` via the public site 21× → 429 on the 21st for *your* IP only; a second network (phone hotspot) still gets 200s. Log via `scripts/dev/test_result.py log`.

## Risks / rollback

- **Secret misconfigured on one side**: system falls back to Fly-Client-IP keying — worker-proxied users share the CF-egress bucket (status quo today, not a regression). Alert path: watch 429 rates after deploy.
- **Webhook ceiling too low**: 600/min is ~10 events/sec sustained from Stripe's IPs; if a legitimate replay burst exceeds it, Stripe retries with backoff — no event loss (webhook processing is idempotent on event id per the audit). Raise the constant if 429s appear in Stripe's dashboard.
- Rollback: revert the PR; secret env vars are inert once the code no longer reads them.

## PR checklist

- [ ] Release note in docs/release-notes/ (per AGENTS.md)
- [ ] TRACKER.md status updated
- [ ] This plan's Status line flipped to DONE
