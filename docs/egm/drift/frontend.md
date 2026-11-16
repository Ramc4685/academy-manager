## frontend/README.md

- [wording] README:3,10 say Next.js 15; frontend/package.json:37 pins `next` 16.4.6 (build is `next build --webpack`, package.json:7).
- [stale-not-built] README:56-58 say CI reports the size-limit gate with `continue-on-error: true`; no workflow under .github/workflows runs `pnpm size` or `lhci` (config at frontend/package.json:73, scripts at :17-18).
- [contract] README:28 says no OpenAPI snapshot is committed; README:88 and frontend/package.json:16 use the committed frontend/lib/api/openapi.snapshot.json, and frontend/lib/api/generated/v2.d.ts is committed (CI diff check at .github/workflows/production.yml:312-320).
- [missing] README:34 lists `components/ui/`; frontend/components/ui does not exist (design system is components/ds).
- [missing] README:41 lists `public/splash/`; it does not exist. README:40 lists a 180 icon; frontend/public/icons has only 192/256/512/maskable.
- [stale-not-built] README:35 says `components/coach` is dynamically imported; frontend/app/(coach)/layout.tsx:14-15 imports it statically.
- [wording] README:52 says the admin shell dynamic-imports the calendar; the `next/dynamic` usages are in page files (app/(admin)/admin/page.tsx, app/(admin)/admin/sessions/page.tsx, app/(coach)/coach/calendar/page.tsx), not frontend/app/(admin)/layout.tsx.
- [wording] README:12 and :14: Radix is only `react-dialog` and `react-slot` (package.json:27-28); Firebase also imports `firebase/app` (frontend/lib/auth/firebase.ts).
- [wording] README:22 puts the public landing under `(marketing)`; it is frontend/app/page.tsx.
- [undocumented] README:21-25 list four route groups; frontend/app also has (owner), (platform), (shared), (student), app/api (csp-report, v2 proxy), app/post-login, app/og-card, app/sw.ts.
- [undocumented] README:26-37 omit many lib/ and components/ folders (lib/admin, coach, design, format, navigation, observability, parent, public-page, tenant, time, ui, waivers; components/announcements, calendar, ds, marketing, messages, observability, pathway, persona, progress, public-page, shared, skills, teaching, waivers).
- [undocumented] README layout and stack omit frontend/middleware.ts, Dockerfile(s), e2e/, scripts/, Capacitor, Sentry, Cloudflare/OpenNext (wrangler.jsonc) and the node/vitest test scripts.
- [wording] README:62-63 say CI audits before typecheck, lint and build; production.yml:310 runs it through scripts/ci/dependency_audit.sh (registry outage becomes a warning), then an OpenAPI drift check, before typecheck.
- [undocumented] README:71-78 name only GHSA-jmr9-qjv8-65gv as a no-patch exception; frontend/pnpm-workspace.yaml:102-108 also ignores GHSA-7pqw-9j4j-h8q3 and GHSA-vfj7-8cjw-p6xm.
- [wording] README:84,86 omit that `dev` honors `$PORT` and uses a worktree port, and `typecheck` runs `next typegen && tsc --noEmit` (package.json:6,13).
