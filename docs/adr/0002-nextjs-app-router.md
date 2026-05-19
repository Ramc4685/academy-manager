# ADR-0002: Next.js 15 App Router replaces CRA

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** RamC (architect)
**Ticket:** P0-02

## Context

The current frontend is **Create React App + React 19 + React Router 7**. CRA has been unmaintained since 2023; the React team's official guidance now points to framework-based tooling. The current bundle ships 64 production dependencies including the full Firebase SDK (~350KB), FullCalendar (~250KB), and Recharts (~200KB) — all eagerly loaded — with **no manifest, no service worker, no route-based code splitting, and no client-side data cache.**

The migration plan requires a fast, installable, mobile-first PWA with persona-specific route groups (coach mobile-first, parent mobile, admin desktop). The coach uses this app on a phone, on court, on bad wifi.

## Decision

Migrate the frontend to **Next.js 15 App Router** and promote it to the canonical `frontend/` directory after cutover. Build it in parallel during migration, then remove the legacy CRA app once production traffic is on Next.js.

- App Router (not Pages Router) for built-in route groups, layouts, RSC where it helps.
- React Server Components for the admin shell (data-dense tables, dashboards).
- Client components for coach (touch, offline) and parent (forms).
- File-based routing under `app/(coach)`, `app/(parent)`, `app/(admin)`, `app/(marketing)`.
- TypeScript strict. shadcn/ui on top of Radix (already in the legacy stack).
- Tailwind for styling — already in use.

## Options Considered

### Option A: Next.js 15 App Router (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Medium — App Router has a learning curve (RSC, server/client boundaries) |
| Cost | ~10 days greenfield scaffold + porting per persona over the wave plan |
| Scalability | High — server-side rendering, image optimization, route splitting built-in |
| Team familiarity | Medium — React experience transfers; App Router idioms are new |
| Risk | Medium |

**Pros:**
- Built-in route groups map cleanly to persona BFFs.
- `next/image` solves the image optimization gap entirely.
- Native PWA support via `next-pwa` or Serwist.
- File-based routing eliminates the `App.js` route table.
- SSR/RSC unlocks the admin perf path without us writing a render layer.
- Mature ecosystem of integrations (TanStack Query, shadcn, Serwist).
- Vercel and self-hosted deployment options; we self-host (Cloudflare Pages with the Vercel adapter or a Node runner).

**Cons:**
- Two routing paradigms to know (legacy CRA + new Next) during the migration window.
- App Router's RSC model is non-trivial; team needs a "how this works" doc (called out as a Wave 1 risk in the plan).
- Self-hosting Next on Cloudflare Pages requires the Next-on-Pages adapter or a Worker runtime — verified to work, but it's a deployment chore.

### Option B: Vite + React + React Router 7 (data APIs)

| Dimension | Assessment |
|---|---|
| Complexity | Low — closest to current code |
| Cost | ~3 days scaffold |
| Scalability | Lower ceiling — no SSR, manual image optimization |
| Team familiarity | High |
| Risk | Low |

**Pros:**
- Fastest migration off CRA. Vite is excellent dev experience.
- React Router 7's data APIs (loader/action) get us much of what App Router offers for routing.
- No new mental model.

**Cons:**
- Manual image optimization, no built-in SSR if admin perf ever needs it.
- PWA tooling is solid (vite-plugin-pwa, Workbox) but requires more wiring than Next's built-ins.
- We will inevitably want SSR or image optimization for admin dashboards. Choosing Vite means a second migration later.

### Option C: Stay on CRA + bolt-on PWA + Workbox + manual splitting

| Dimension | Assessment |
|---|---|
| Complexity | Medium — lots of manual wiring against unmaintained tooling |
| Cost | ~1 week |
| Scalability | Worst |
| Team familiarity | Highest |
| Risk | Medium-high — CRA is unmaintained, ecosystem drift accumulates |

**Pros:** Cheapest in the short term. No new frameworks to learn.

**Cons:**
- We inherit all the existing perf problems (no SSR, no image optimization, no route groups).
- Tech debt grows as CRA's plugin ecosystem rots. webpack 5 + craco overrides are fragile.
- Doesn't meet the architectural goal — we'd be building the BFF underneath a frontend that can't fully exploit it.

### Option D: Remix (Vite-based)

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Cost | Similar to Next |
| Scalability | High |
| Team familiarity | Low |
| Risk | Medium-high |

**Pros:** Excellent data-loading model; nested routing maps cleanly to personas.
**Cons:** Smaller ecosystem; no shadcn-of-Remix scale story; team has no Remix experience. Rejected on familiarity + ecosystem.

## Trade-off Analysis

The choice is between **Next (highest ceiling, medium learning cost)**, **Vite (lowest cost, lower ceiling)**, and **CRA (cheapest but architecturally wrong)**.

CRA is rejected because the architectural goals require capabilities CRA does not have (route groups, SSR for admin, image optimization). Choosing it means we re-migrate later.

Vite is the strongest alternative. The deciding factor is **admin perf and image optimization** — both of which Next gives us out of the box and which we will need by Wave 3. Choosing Vite means writing those ourselves or migrating again. The cost differential (~7 days extra for Next) is paid back across waves.

The cost of Next's learning curve is real but is bounded: Wave 1A is a small slice that doubles as paired learning; ADR-0005 and the "how this works" doc land before Wave 2 opens.

## Consequences

**Becomes easier:**
- Persona route groups via `app/(coach)`, `app/(parent)`, `app/(admin)`.
- Image optimization is free (`next/image`).
- SSR/RSC available where it pays (admin tables).
- PWA tooling (Serwist + Next config) is well-trodden.
- Code splitting is automatic per route segment.

**Becomes harder:**
- The team must internalize the RSC server/client boundary. Mistakes will leak heavy modules into client bundles. CI bundle-size gates catch most of these.
- Self-hosting Next on Cloudflare requires the adapter; deployment runbook covers it.

**To revisit:**
- If self-hosting Next on Cloudflare becomes operationally painful, an ADR may move us to Vercel or a Node runtime on Fly.
- If RSC's complexity costs us velocity disproportionate to the perf wins, we'd revisit by Wave 3.

## Action Items

1. [x] Reject Vite, CRA-bolt-on, and Remix.
2. [ ] Scaffold `frontend/` with App Router (P0-17).
3. [ ] Write a Wave-1A handoff doc that explains RSC vs client component boundaries.
4. [ ] Verify Cloudflare Pages adapter end-to-end before Wave 1A starts (P0-20).
