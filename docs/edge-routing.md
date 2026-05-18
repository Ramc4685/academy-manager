# Edge Routing Runbook

**Status:** Retired for production. Historical routing logic remains in
[`edge/router.ts`](../edge/router.ts) for reference and local experiments.
**Last reviewed:** 2026-05-18

Production browser traffic now goes directly to the `academy-next` Cloudflare
Worker through the custom domain in
[`frontend-next/wrangler.jsonc`](../frontend-next/wrangler.jsonc). The Next app
rewrites `/api/v2/*` to the FastAPI BFF origin.

## Former Decisions

`edge/router.ts` exports a pure `decide(url, env)` function:

1. `/api/*` routes to `API_ORIGIN`.
2. Every other path routes to `WEB_ORIGIN`.

This was useful during cutover, but the extra Worker route can conflict with the
single frontend custom domain and should not be deployed in production.

## Required Vars

| Var | Production example |
|---|---|
| `API_ORIGIN` | `https://api.academy.courtmastr.com` |
| `WEB_ORIGIN` | `https://academy.courtmastr.com` |

The base `[vars]` in `edge/wrangler.toml` are local-development defaults.
Production values live under `[env.prod.vars]`, but the production GitHub
workflow no longer deploys this Worker.

There are no per-persona legacy flags in production anymore. Admin, coach,
parent, login, and registration all live in `frontend-next/`.

## Deploy

Do not deploy `academy-edge-router` for production. The production GitHub
workflow deletes the old Worker route before deploying `frontend-next/`.

## Tests

```bash
cd edge
npx tsx router.test.ts
```

The test suite asserts that API paths go to the API origin and all browser,
asset, and persona paths go to the Next frontend origin.
