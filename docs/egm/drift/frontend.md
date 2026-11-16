## frontend/README.md

- [contract] README:3,10 say Next.js 15 (ADR-0002 also says 15); `frontend/package.json:37` pins `next` 16.4.6.
- [stale-not-built] README:28 says `lib/api/generated/` has "currently no snapshot is committed"; `frontend/lib/api/openapi.snapshot.json` and `frontend/lib/api/generated/v2.d.ts` are committed. CI diffs them (`.github/workflows/production.yml:312-320`), and README:88 itself says `generate:api` reads the committed snapshot.
- [stale-not-built] README:41 lists `public/splash/` (iOS splash screens). `frontend/public/` has only `favicon.ico`, `icons/` and `manifest.webmanifest`, with no `splash/`. The icons are `icon-192/256/512/maskable.png`, and no 180 icon exists (README:40).
- [stale-not-built] README:34 lists `components/ui/` (touch-sized primitives). It does not exist; the primitives live in `frontend/components/ds/`.
- [stale-not-built] README:56-58 says the CI workflow reports the size-limit gate with `continue-on-error: true`. No workflow runs `pnpm size` or `size-limit`, and `.github/workflows/production.yml` has no `continue-on-error`. Budgets exist only in `frontend/package.json:73-88`.
- [stale-not-built] README:62-63 says the audit runs before typecheck, lint and build. The audit does run first (`production.yml:308-310`), but the step goes through `scripts/ci/dependency_audit.sh`, which turns a registry outage into a warning. README says nothing about this.
- [stale-not-built] README:23 says coach has "teaching-plan flows". The only match is `frontend/app/(coach)/coach/today/plan`, and the README describes no teaching-plan route group.
- [undocumented] README:21-25 and 44 list four route groups (marketing, coach, parent, admin). `frontend/app` also has `(owner)`, `(platform)`, `(shared)` (calendar, messages) and `(student)`, plus `app/api`.
- [undocumented] README:26-32 omits `lib/` subtrees that exist: `admin`, `coach`, `design`, `format`, `navigation`, `observability`, `parent`, `public-page`.
- [undocumented] README:33-37 omits `components/` subtrees `announcements`, `calendar`, `ds`, `marketing`, `messages`, `observability`, `pathway`, `persona`, `progress`, `public-page`, `shared`, `skills`, `teaching`, `waivers`.
- [undocumented] README:8-16 omits the Capacitor native-app layer (`@capacitor-firebase/authentication` and `messaging`, `@capacitor/core`, `frontend/package.json:24-26`, `frontend/lib/auth/native-sign-in.ts`, `native-push.ts`) and Sentry (`@sentry/browser`, `frontend/components/observability/sentry-init.tsx`). Cloudflare/OpenNext deploy (`frontend/open-next.config.ts`, `wrangler.jsonc`) is also undocumented.
- [wording] README:14 says Firebase "modular `firebase/auth` only"; `frontend/lib/auth/firebase.ts:9` also imports `firebase/app`.
- [wording] README:12 says Tailwind + Radix + shadcn-style primitives; the only Radix packages are `react-dialog` and `react-slot` (`package.json:27-28`), and the primitives are the custom `components/ds` set. Tailwind is v4 (`package.json:68`).
- [wording] README:85 says `pnpm build` is a "production build"; `package.json:7` is `next build --webpack` (required for Serwist). README:86 says `pnpm typecheck` is `tsc --noEmit`; `package.json:13` is `next typegen && tsc --noEmit`.
- [missing] README:80-91 does not list the test and e2e scripts (`test:unit`, `test:node`, `e2e`, `e2e:local-auth`, `e2e:ui`; `package.json:12-21`), which CI runs.
