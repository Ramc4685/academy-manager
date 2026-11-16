## frontend/README.md

- [wording] README:3,10,16 (and ADR-0002) say Next.js 15; code is Next 16.4.6 (frontend/package.json:37).
- [contract] README:84 says `pnpm dev` is `next dev (Turbopack)`; true for dev (package.json:6) but `pnpm build` is `next build --webpack` (package.json:7), which README:85 does not say.
- [contract] README:86 `pnpm typecheck` is `tsc --noEmit`; actual is `next typegen && tsc --noEmit` (package.json:13).
- [contract] README:88 says `generate:api` reads `openapi.snapshot.json` (and README:28 says no snapshot is committed). Script reads `lib/api/openapi.snapshot.json` (package.json:16), which exists, and `lib/api/generated/v2.d.ts` is committed (frontend/lib/api/generated/v2.d.ts). README:28 is stale.
- [stale-not-built] README:41 lists `public/splash/` iOS splash screens; directory does not exist (frontend/public has only favicon.ico, icons, manifest.webmanifest).
- [stale-not-built] README:34 lists `components/ui/` touch-sized primitives; no such directory (frontend/components has `ds/` and `shared/` instead).
- [stale-not-built] README:40 icons "180/192/256/512/maskable"; frontend/public/icons has no 180 icon (192, 256, 512, maskable only).
- [stale-not-built] README:56-58 says CI reports the size-limit gate with `continue-on-error: true`; no `pnpm size` or `lhci` step exists in .github/workflows/production.yml (size-limit config exists at frontend/package.json:73).
- [stale-not-built] README:62-63 says the audit runs in the "Frontend Static job" before typecheck, lint and build; it runs via scripts/ci/dependency_audit.sh (.github/workflows/production.yml:310), which treats registry outages as non-failures unless AUDIT_STRICT=1, a nuance the README omits. (Order matches.)
- [undocumented] README:20-25 and 44-52 list four route groups; code also has `(owner)`, `(platform)`, `(shared)`, `(student)` with their own layouts (frontend/app/(owner)/layout.tsx:1, (platform)/layout.tsx, (shared)/layout.tsx, (student)/layout.tsx).
- [undocumented] README:33-37 omits many component dirs (admin-adjacent `announcements`, `calendar`, `ds`, `marketing`, `messages`, `pathway`, `persona`, `progress`, `public-page`, `skills`, `teaching`, `waivers`, `observability`, `shared`) and lib/ domains (`lib/admin`, `lib/coach`, `lib/parent`, `lib/navigation`, `lib/design`, etc.); also `middleware.ts`, `open-next.config.ts`, `wrangler.jsonc` (Cloudflare/OpenNext deploy) are not mentioned.
- [wording] README:23 `(coach)` and README:52 "coach shell has no calendar lib" while frontend/app/(coach)/coach/calendar/page.tsx:17 dynamically imports a calendar view; README:35 says `components/coach` is dynamically imported but only some usages are (coach/calendar/page.tsx:5).
- [wording] README:12 "Tailwind + Radix": Tailwind is v4 via @tailwindcss/postcss (package.json:55) and Radix usage is limited to dialog and slot (package.json:27-28).
