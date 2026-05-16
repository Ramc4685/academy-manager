# Edge Routing Runbook

**Status:** Authoritative. Implemented by the Cloudflare Worker at [`edge/router.ts`](../edge/router.ts).
**Ticket:** P0-20
**Last reviewed:** 2026-05-16

The edge router is the migration's hinge: it decides whether each request is served by the **legacy** stack (CRA + procedural FastAPI routers) or the **v2** stack (Next.js App Router + clean-architecture FastAPI v2). Cutovers are env-var flips on the worker — **never code deploys.**

## How decisions are made

`edge/router.ts` exports a pure `decide(url, env)` that returns a `Decision`:

- `proxy → <origin>` — forward the request to the legacy or v2 origin.
- `gone` — return 410 (used in Wave 4A when a legacy API path is decommissioned).

Decisions are made in this order:

1. `/api/v2/*` → always v2 API origin.
2. `/api/*` → legacy API origin (or 410 if `FLAG_LEGACY_API_GONE=1`).
3. Persona prefixes (`/coach/*`, `/parent/*`, `/admin/*`) → per-flag.
4. Marketing (`/login`, `/`) → per `FLAG_V2_MARKETING`.

## The flags

| Flag | Values | Set in |
|---|---|---|
| `FLAG_V2_MARKETING` | `legacy` \| `v2` | wrangler.toml + `wrangler secret` |
| `FLAG_COACH_TODAY` | `legacy` \| `v2` | Set to `v2` during W1A-20 canary |
| `FLAG_COACH_ALL` | `legacy` \| `v2` | Flipped after Wave 1B + remaining coach surfaces migrate |
| `FLAG_PARENT_ALL` | `legacy` \| `v2` | Wave 2 cutover |
| `FLAG_ADMIN_ALL` | `legacy` \| `v2` | Wave 3 cutover |
| `FLAG_LEGACY_API_GONE` | `0` \| `1` | Wave 4A — returns 410 for legacy `/api/*` |

## Cutover procedure (W1A-20 reference)

1. **Pre-flight:** Wave 1A exit checklist items 1–4 complete in staging.
2. **Canary 10%:** Use Cloudflare's per-deployment percentage split — push a worker version with `FLAG_COACH_TODAY=v2`, route 10% of traffic to it.
3. **Soak 1h:** Watch RED metrics (p95 read <300ms, p95 write <800ms, error rate ≤ baseline). Web Vitals (LCP/CLS/INP) within budget. Install events look normal.
4. **Flip 100%:** Promote the worker version to 100%.
5. **Soak 1 week** before Wave 1B planning opens.

## Rollback

```bash
# Roll back coach traffic to legacy in one command.
wrangler secret put FLAG_COACH_TODAY --env prod
# Enter: legacy
```

Worker secrets propagate within ~30s globally. No code deploy.

## What the worker does not do

- **It does not enforce auth.** Origins authenticate themselves (Firebase tokens to FastAPI; cookies for legacy).
- **It does not enforce rate limits.** That stays at the origin until per-persona limits become a real need.
- **It does not transform bodies.** Pure proxy — request and response bodies pass through untouched.

## Deploy

```bash
cd edge
wrangler deploy           # production
wrangler deploy --env preview
```

## Tests

```bash
cd edge
node --import tsx router.test.ts
```

The test suite asserts the routing table (legacy default, per-flag flips, 410 for `FLAG_LEGACY_API_GONE`). The test file is intentionally framework-free; a Wrangler-aware Vitest pool will replace it when we add origin fetch tests.
