## frontend/README.md

- [wording] README:3,10 say Next.js 15; code pins Next 16.4.6 (frontend/package.json:37, eslint-config-next 16.4.6 at :63).
- [wording] README:84 says `pnpm dev` is Turbopack on :3001 (matches, frontend/package.json:6), but `pnpm build` (README:85) is `next build --webpack` (frontend/package.json:7); webpack is deliberate (service worker) and undocumented.
- [contract] README:28 says `lib/api/generated/` has no committed snapshot; code commits `frontend/lib/api/openapi.snapshot.json` and `frontend/lib/api/generated/v2.d.ts`. README:88 (committed snapshot) contradicts README:28.
- [stale-not-built] README:35 and README:34 list `components/ui/` (touch-sized primitives); the directory does not exist (frontend/components has ds/, shared/, etc.).
- [stale-not-built] README:41 lists `public/splash/` iOS splash screens; frontend/public contains only favicon.ico, icons/, manifest.webmanifest.
- [stale-not-built] README:40 lists a 180px icon; frontend/public/icons has 192/256/512/maskable only (no 180).
- [stale-not-built] README:56-58 say CI reports the size-limit gate with `continue-on-error: true`; no workflow in .github/workflows runs `pnpm size` or `lhci` (budgets only in frontend/package.json:73-88, all 360 KB).
- [stale-not-built] README:12 / README:23-24 ("coach-only, dynamically imported" components/coach; coach shell has "no calendar lib"): only calendar/admin chart components use `dynamic(`; components/coach is not dynamically imported as a rule (components/calendar/PersonaCalendarView.tsx, components/admin/AdminCalendarView.tsx).
- [wording] README:12 says Tailwind + Radix + shadcn-style primitives; only @radix-ui/react-dialog and react-slot are used (frontend/package.json:27-28), Tailwind is v4.
- [wording] README:62 says CI runs `pnpm audit --audit-level=high` directly; it runs through `scripts/ci/dependency_audit.sh` (a registry outage becomes a warning) at .github/workflows/production.yml:310.
- [undocumented] Route groups `(owner)`, `(platform)`, `(shared)`, `(student)` exist (frontend/app/) but README:21-25 lists only marketing/coach/parent/admin.
- [undocumented] Capacitor native shell dependencies (@capacitor-firebase/authentication, messaging; frontend/package.json:24-25), Cloudflare/OpenNext deploy scripts (package.json:8-10), vitest, node tests and Playwright e2e scripts (package.json:14-22) are not in README Stack or Scripts.
- [undocumented] README:14 says Firebase `firebase/auth` only; lib/auth also holds native sign-in/push code (frontend/lib/auth/native-sign-in.ts, native-push.ts).
