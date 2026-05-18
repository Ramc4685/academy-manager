# Edge Routing Runbook

**Status:** Authoritative. Implemented by the Cloudflare Worker at
[`edge/router.ts`](../edge/router.ts).
**Last reviewed:** 2026-05-18

The edge router is now a thin production router, not a legacy/v2 traffic
splitter.

## Decisions

`edge/router.ts` exports a pure `decide(url, env)` function:

1. `/api/*` routes to `API_ORIGIN`.
2. Every other path routes to `WEB_ORIGIN`.

This keeps `academy.courtmastr.com` on one frontend while preserving same-host
API routing where needed.

## Required Vars

| Var | Production example |
|---|---|
| `API_ORIGIN` | `https://courtmastr-academy-api.fly.dev` |
| `WEB_ORIGIN` | `https://academy-next.courtmastr.com` |

The base `[vars]` in `edge/wrangler.toml` are local-development defaults.
Production values live under `[env.prod.vars]` and are used by the GitHub
deployment command.

There are no per-persona legacy flags in production anymore. Admin, coach,
parent, login, and registration all live in `frontend-next/`.

## Deploy

```bash
npx wrangler@4 deploy --config edge/wrangler.toml --env prod
```

The production GitHub workflow deploys the edge worker after the Fly backend
and Next frontend deploy successfully.

## Tests

```bash
cd edge
npx tsx router.test.ts
```

The test suite asserts that API paths go to the API origin and all browser,
asset, and persona paths go to the Next frontend origin.
