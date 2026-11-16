## frontend/README.md

- [contract] README:3,10 (and ADR title) say Next.js 15; code is Next 16.4.6 (frontend/package.json:37). `build` uses `next build --webpack` (package.json:7), also undocumented.
- [contract] README:28 says no OpenAPI snapshot is committed under generated/; frontend/lib/api/generated/v2.d.ts and frontend/lib/api/openapi.snapshot.json are committed, and CI checks drift (.github/workflows/production.yml:312). README:88 correctly says "committed", so the two lines contradict each other. The snapshot lives at lib/api/openapi.snapshot.json (package.json:16), not stated.
- [stale-not-built] README:40 lists icon size 180; frontend/public/icons has only icon-192/256/512/maskable (180 absent).
- [stale-not-built] README:41 `public/splash/` (iOS splash screens); frontend/public/splash does not exist.
- [stale-not-built] README:34 `components/ui/` (touch-sized primitives); does not exist. The primitives live in frontend/components/ds/ (e.g. components/ds/avatar.tsx).
- [stale-not-built] README:56-58 says CI reports the size-limit gate with `continue-on-error: true`; no workflow runs `pnpm size` or `lhci` (grep of .github finds none; Frontend Static job at production.yml:277-354). Budgets exist at package.json:73-89 (360 KB each).
- [wording] README:12 says "Tailwind + Radix + shadcn-style primitives"; only @radix-ui/react-dialog and react-slot are installed (package.json:27-28), and Tailwind is v4 via @tailwindcss/postcss.
- [undocumented] README:21-25 lists four route groups; app/ also has (owner), (platform), (shared), (student) (frontend/app/). Marketing also has register, privacy, terms, security, unsubscribe, account-deletion, auth.
- [undocumented] app/sw.ts (service worker source), middleware.ts, open-next.config.ts and wrangler.jsonc (Cloudflare Worker deploy via OpenNext), vitest and playwright configs. README:15 mentions Serwist only.
- [undocumented] lib/ has many more areas than README:26-32: lib/api/v2 (own README), lib/admin, lib/coach, lib/parent, lib/format, lib/navigation, lib/observability, lib/design.
- [undocumented] components/ has announcements, calendar, ds, marketing, messages, observability, pathway, persona, progress, public-page, shared, skills, teaching, waivers beyond the README:33-37 listing (ui/coach/parent/admin).
- [undocumented] README:14 omits firebase/app (frontend/lib/auth/firebase.ts:9), though README says "firebase/auth only".
