## frontend/README.md

- [wording] README:3,10 says Next.js 15; `frontend/package.json:37` pins `next` 16.4.6.
- [contract] README:28 says no OpenAPI snapshot is committed under `lib/api/generated/`; `frontend/lib/api/generated/v2.d.ts` and `frontend/lib/api/openapi.snapshot.json` are committed, CI checks them for drift (`.github/workflows/production.yml:312-320`), and README:88 itself says the snapshot is committed.
- [undocumented] README:20-25 lists four route groups; `frontend/app/` also has `(owner)`, `(platform)`, `(shared)` (calendar, messages) and `(student)`, each with a `layout.tsx`.
- [wording] README:22-23 lists only the `(marketing)` pages "landing, login"; `frontend/app/(marketing)/` also has account-deletion, auth, privacy, register, security, terms and unsubscribe.
- [stale-not-built] README:34 and 38-41: `frontend/components/ui/` does not exist (only `frontend/lib/ui/` does). The components dirs are `admin`, `announcements`, `calendar`, `coach`, `ds`, `marketing`, `messages`, `observability`, `parent`, `pathway`, `persona`, `progress`, `public-page`, `shared`, `skills`, `teaching`, `waivers`.
- [stale-not-built] README:41 `public/splash/` (iOS splash screens) does not exist. `frontend/public/` has only `favicon.ico`, `icons/`, `manifest.webmanifest`.
- [wording] README:40 lists icons "180/192/256/512/maskable"; `frontend/public/icons/` has 192, 256, 512 and maskable only, with no 180.
- [wording] README:35 says `components/coach` is "dynamically imported"; no `next/dynamic` use was found in `frontend/app/(coach)/coach/today/page.tsx` or `frontend/components/coach/*`. The only coach dynamic import is the calendar view (`frontend/app/(coach)/coach/calendar/page.tsx:17`).
- [wording] README:52 says the coach shell has "no calendar lib"; the coach layout links `/coach/calendar` (`frontend/app/(coach)/layout.tsx:195`) and that page loads `PersonaCalendarView`.
- [wording] README:12 says "Tailwind + Radix + shadcn-style primitives"; Radix is only `@radix-ui/react-dialog` and `react-slot` (`frontend/package.json:27-28`). Tailwind is v4 via `@tailwindcss/postcss`.
- [undocumented] `frontend/package.json:24-25` depends on Capacitor Firebase auth and messaging (native sign-in, `frontend/lib/auth/native-sign-in.ts`); README:14 lists only the web SDK. OpenNext/Cloudflare (`open-next.config.ts`, `wrangler.jsonc`) is not mentioned.
- [undocumented] README:84-85 `pnpm build` is `next build --webpack` (`frontend/package.json:7`), not the default builder. The README does not say so, and the Next 16 default is Turbopack.
- [stale-not-built] README:56-58 says CI reports the size-limit bundle gate with `continue-on-error: true`; no workflow under `.github/workflows/` runs `pnpm size` or `size-limit`, and nothing there sets `continue-on-error`.
- [stale-not-built] README:90 `pnpm lhci` is documented, but no CI workflow runs Lighthouse; the script exists at `frontend/package.json:18`. It is only a local script.
- [wording] README:62 says the audit runs via `pnpm audit --audit-level=high`; CI runs it through `scripts/ci/dependency_audit.sh` (`.github/workflows/production.yml:310`), which turns a registry outage into a warning.
- [wording] README:26-32 `lib/` layout omits many top-level areas such as `lib/admin`, `lib/coach`, `lib/parent`, `lib/design`, `lib/format`, `lib/navigation` and `lib/observability`. `lib/api/` also has a nested `v2/` with its own README.
