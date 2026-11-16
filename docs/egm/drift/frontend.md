## frontend/README.md

- [wording] README:3,10 says Next.js 15; `frontend/package.json:37` pins `next` 16.4.6.
- [contract] README:28 says no OpenAPI snapshot is committed under `lib/api/generated/`; `frontend/lib/api/generated/v2.d.ts` and `frontend/lib/api/openapi.snapshot.json` are committed (both modified in this worktree), CI checks them for drift (`.github/workflows/production.yml:312-320`), and README:88 itself says the snapshot is committed.
- [undocumented] README:20-25 lists four route groups; `frontend/app/` also has `(owner)`, `(platform)`, `(shared)` (calendar, messages) and `(student)`.
- [wording] README:22-23 lists only `(marketing)` "landing, login"; `frontend/app/(marketing)/` also has account-deletion, auth, privacy, register, security, terms and unsubscribe.
- [undocumented] The admin billing-health page (`frontend/app/(admin)/admin/billing-health/page.tsx:432-434, 495-578`) gained `OpenDisputesCard` and `RefundFailuresCard`, plus a "Stripe carries fees and losses" row and `payments_blocked_reason` detail (`:812-848`), backed by new types in `frontend/lib/api/admin.ts:2400-2466` and an `autopay_stuck` attention kind (`admin.ts:1375`). README does not describe the billing-health surface or the billing contract it renders.
- [undocumented] `frontend/lib/billing-rules-form.ts:130` now accepts negative integers in `inputToDays` (`/^-?\d+$/`), so the reminder-days list can hold negatives. README says nothing about the billing rules form.
- [wording] `frontend/components/admin/settings/notify-panel.tsx:97-99` now says "Payment reminder emails ... Billing rules" and "Payment reminder days". The Billing rules panel (`frontend/components/admin/settings/billing-rules-panel.tsx:220`, `frontend/lib/billing-rules-form.ts:33`) still names the field `reminder_days`, and its label comes from the backend row, so the renamed copy cannot be confirmed from frontend code.
- [stale-not-built] README:34 and 38-41: `frontend/components/ui/` does not exist. The components dirs are `admin`, `announcements`, `calendar`, `coach`, `ds`, `marketing`, `messages`, `observability`, `parent`, `pathway`, `persona`, `progress`, `public-page`, `shared`, `skills`, `teaching`, `waivers`.
- [stale-not-built] README:41 `public/splash/` (iOS splash screens) does not exist. `frontend/public/` has only `favicon.ico`, `icons/`, `manifest.webmanifest`.
- [wording] README:40 lists icons "180/192/256/512/maskable"; `frontend/public/icons/` has 192, 256, 512 and maskable only, with no 180.
- [wording] README:11 says "RSC for admin"; 35 of 51 `frontend/app/(admin)/**/page.tsx` files start with `"use client"`, including billing-health (`page.tsx:1`).
- [wording] README:35 says `components/coach` is "dynamically imported"; the only coach `next/dynamic` use is the calendar view (`frontend/app/(coach)/coach/calendar/page.tsx`).
- [wording] README:52 says the coach shell has "no calendar lib"; the coach layout links `/coach/calendar` (`frontend/app/(coach)/layout.tsx:195`), which loads `PersonaCalendarView`.
- [wording] README:12 says "Tailwind + Radix + shadcn-style primitives"; Radix is only `@radix-ui/react-dialog` and `react-slot` (`frontend/package.json:27-28`). Tailwind is v4 via `@tailwindcss/postcss`.
- [undocumented] `frontend/package.json:24-25` depends on Capacitor Firebase auth and messaging (`frontend/lib/auth/native-sign-in.ts`); README:14 lists only the web SDK. OpenNext/Cloudflare (`open-next.config.ts`, `wrangler.jsonc`) is not mentioned.
- [undocumented] README:84-85 `pnpm build` is `next build --webpack` (`frontend/package.json:7`), not the Next 16 default (Turbopack). Not mentioned. `pnpm typecheck` also runs `next typegen` first (`package.json:13`).
- [stale-not-built] README:56-58 says CI reports the size-limit gate with `continue-on-error: true`; no workflow under `.github/workflows/` runs `pnpm size` or `size-limit`, and none sets `continue-on-error`.
- [stale-not-built] README:90 `pnpm lhci` is documented, but no CI workflow runs Lighthouse; it exists only as a local script (`frontend/package.json:18`).
- [wording] README:62 says CI runs `pnpm audit --audit-level=high`; CI goes through `scripts/ci/dependency_audit.sh` (`.github/workflows/production.yml:309-310`), which turns a registry outage into a warning.
- [wording] README:26-32 `lib/` layout omits `lib/admin`, `lib/coach`, `lib/design`, `lib/format` and many top-level helpers (for example `billing-health.ts`, `billing-rules-form.ts`). `lib/api/` also has a nested `v2/` with its own README.
- [wording] README:3,10 say "Next.js 15"; `frontend/package.json:37` pins `next` 16.4.6.
- [wording] README:14 says "modular `firebase/auth` only"; `frontend/lib/auth/firebase.ts` also imports `firebase/app`.
- [stale-not-built] README:28 says no OpenAPI snapshot is committed under `lib/api/generated`; `frontend/lib/api/generated/v2.d.ts` and `frontend/lib/api/openapi.snapshot.json` are committed, and `.github/workflows/production.yml:312` (OpenAPI drift check) enforces them. README:88 correctly describes the snapshot, so the two lines contradict each other.
- [stale-not-built] README:34 lists `components/ui/` (touch-sized primitives); the directory does not exist. Primitives live in `frontend/components/ds/` (`ds/index.ts`).
- [stale-not-built] README:41 lists `public/splash/` (iOS splash screens); `frontend/public/splash` does not exist (`frontend/public` has only `favicon.ico`, `icons/`, `manifest.webmanifest`).
- [stale-not-built] README:54-58 says CI reports the size-limit gate with `continue-on-error: true`; no workflow under `.github/` runs `pnpm size` or `lhci` (see `.github/workflows/production.yml` frontend job). The `size-limit` config exists at `frontend/package.json:73-92`, with a 360 KB limit on each of the three chunks.
- [undocumented] README:21-25 lists four route groups; `frontend/app/` also has `(owner)`, `(platform)`, `(student)` and `(shared)`, each with its own `layout.tsx`.
- [undocumented] README:33-37 lists `components/ui|coach|parent|admin`; `frontend/components/` also has `ds`, `calendar`, `public-page`, `marketing`, `messages`, `pathway`, `persona`, `progress`, `skills`, `teaching`, `waivers`, `announcements`, `observability` and `shared`.
- [undocumented] README:26-32 lists five `lib/` subfolders; `frontend/lib/` also has `admin`, `coach`, `parent`, `design`, `format`, `navigation`, `observability`, `public-page`, `tenant`, `time`, `ui` and `waivers`, plus many top-level modules.
- [wording] README:23 mentions coach "teaching-plan flows"; no such route exists under `frontend/app/(coach)/coach/` (L8 billing-calendar check, 2026-11-16).

Re-checked 2026-11-16 against the coach-attendance change (fix/coach-attendance, incl. review fix rounds and contrast test): no new drift; items above still hold.
