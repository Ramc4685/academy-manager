## frontend/README.md

- [wording] README:3, :10 say "Next.js 15"; `frontend/package.json:37` pins `next` 16.4.6.
- [stale-not-built] README:34 lists `components/ui/` (touch-sized primitives); no such directory. Primitives live in `frontend/components/ds/`.
- [stale-not-built] README:41 lists `public/splash/` (iOS splash screens); directory does not exist (`frontend/public/` has only `favicon.ico`, `icons/`, `manifest.webmanifest`).
- [stale-not-built] README:56-58 says CI reports the size-limit gate with `continue-on-error: true`; no workflow under `.github/workflows/` runs `pnpm size`/size-limit (budgets exist only at `frontend/package.json:73-90`). `pnpm lhci` (README:90) likewise has no CI step.
- [wording] README:23 says coach group has "teaching-plan flows"; `frontend/app/(coach)/coach/` has only `calendar, messages, needs-review, profile, sessions, students, today`.
- [wording] README:52 says the admin layout dynamic-imports the calendar; the dynamic import is in `frontend/app/(admin)/admin/sessions/page.tsx:45`, not `frontend/app/(admin)/layout.tsx`.
- [undocumented] README:20-25 lists four route groups; code also has `frontend/app/(owner)`, `(platform)`, `(shared)`, `(student)`.
- [undocumented] README layout (18-42) omits `frontend/app/api`, `app/post-login`, `app/og-card`, `app/sw.ts`, `frontend/middleware.ts`, the Cloudflare/OpenNext deploy files (`open-next.config.ts`, `wrangler.jsonc`), and many `components/*` (`ds`, `calendar`, `messages`, `pathway`, `skills`, `teaching`, `waivers`, ...) and `lib/*` dirs (`admin`, `coach`, `tenant`, `time`, `observability`, ...).
- [undocumented] `frontend/package.json:7` builds with `next build --webpack` (needed for the service worker); README:85 only says "production build".
