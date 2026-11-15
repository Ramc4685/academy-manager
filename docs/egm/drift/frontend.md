## frontend/README.md

- [contract] README:3,10 say Next.js 15; frontend/package.json:37 pins next 16.4.6.
- [contract] README:28 says no OpenAPI snapshot is committed under lib/api/generated; frontend/lib/api/generated/v2.d.ts and frontend/lib/api/openapi.snapshot.json are committed, and README:88 itself says generate:api reads the committed snapshot (self-contradiction).
- [stale-not-built] README:35 lists components/ui/ (touch-sized primitives); frontend/components/ has no ui/ directory (closest is components/ds/).
- [stale-not-built] README:41 lists public/splash/ iOS splash screens; frontend/public/ has no splash/ directory.
- [stale-not-built] README:57-58 says the CI workflow reports the size-limit gate with continue-on-error; no workflow under .github/workflows runs size-limit (frontend/package.json:17,73 define it only).
- [stale-not-built] README:52 says the admin shell dynamic-imports the calendar; frontend/app/(admin)/layout.tsx has no next/dynamic use (dynamic imports are in app/(admin)/admin/page.tsx and app/(admin)/admin/sessions/page.tsx).
- [wording] README:62 says `pnpm audit --audit-level=high` runs directly; .github/workflows/production.yml:310 wraps it in scripts/ci/dependency_audit.sh (registry outage warns, findings fail).
- [undocumented] README:20-25 lists four route groups; frontend/app also has (owner), (platform), (shared) and (student).
- [undocumented] README:26-32 and 33-37 omit frontend/lib/admin and the components subfolders announcements, calendar, ds, marketing, messages, observability, persona, pathway, progress, public-page, shared, skills, teaching, waivers.
- [undocumented] README:14 and stack list omit Capacitor native auth/messaging (frontend/package.json:24-25) and OpenNext/Cloudflare deploy (frontend/open-next.config.ts, frontend/wrangler.jsonc); README:84 says `pnpm dev` uses Turbopack while `pnpm build` uses `next build --webpack` (package.json:6-7), which is not mentioned.
