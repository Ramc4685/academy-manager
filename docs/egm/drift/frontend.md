## frontend/README.md

- [wording] README:3,10 say Next.js 15; frontend/package.json:37 pins `next` 16.4.6.
- [wording] README:12 says Tailwind; frontend/package.json:55,68 is Tailwind 4 with `@tailwindcss/postcss`. Only a version-level difference.
- [stale-not-built] README:35 lists `components/ui/` (touch-sized primitives); the directory does not exist. The primitives live in `frontend/components/ds/` (button.tsx, card.tsx, modal.tsx, ...).
- [missing] README:36-37 lists `components/parent/` and `components/admin/` only. The code also has components/{announcements,calendar,ds,marketing,messages,observability,pathway,persona,progress,public-page,shared,skills,teaching,waivers}.
- [stale-not-built] README:41 lists `public/splash/` (iOS splash screens); `frontend/public/` has only favicon.ico, icons/, manifest.webmanifest.
- [stale-not-built] README:40 lists icon sizes 180/192/256/512/maskable; `frontend/public/icons/` has no icon-180.png (frontend/public/icons/README.md also requires it).
- [undocumented] README:21-25 lists 4 route groups. The code also has `app/(owner)`, `app/(platform)`, `app/(shared)` and `app/(student)`, each with its own layout.tsx (frontend/app/*/layout.tsx).
- [undocumented] README:22 says marketing is "public landing, login". `frontend/app/(marketing)/` also holds account-deletion, auth, privacy, register, security, terms, unsubscribe.
- [wording] README:28 says no OpenAPI snapshot is committed. `frontend/lib/api/openapi.snapshot.json` and `frontend/lib/api/generated/v2.d.ts` are both committed. README:88 says "committed openapi.snapshot.json", which contradicts line 28.
- [contract] README:88 says `pnpm generate:api` reads `openapi.snapshot.json`. The script (frontend/package.json:16) reads `lib/api/openapi.snapshot.json` (the path is not stated). It also writes `lib/api/generated/v2.d.ts`, which is consistent.
- [stale-not-built] README:56-58 says CI reports the size-limit gate with `continue-on-error: true`. No workflow runs `pnpm size` or lhci (grep of .github/workflows finds no size-limit, lhci or continue-on-error). The budgets exist only in frontend/package.json:73-89 (360 KB each).
- [wording] README:14 says "modular `firebase/auth` only". frontend/lib/auth/firebase.ts:9 also imports `firebase/app`. The code also uses `@capacitor-firebase/authentication` and `@capacitor-firebase/messaging` (frontend/lib/auth/native-sign-in.ts:98, native-push.ts:82).
- [undocumented] README:82-91 scripts omit `test`/e2e scripts and the `typecheck` prefix `next typegen &&` (frontend/package.json:13). README:86 says `tsc --noEmit` only. README:84 omits that the default port can be overridden by `$PORT` (package.json:6), and README:85 omits that `build` is `next build --webpack` (package.json:7).
- [missing] README:26-32 lists `lib/` subfolders only. `frontend/lib/` also has admin, coach, design, format, navigation, observability, parent, public-page, tenant, time, ui and waivers, plus many top-level modules. `lib/api/v2/` exists (it has its own README).
- [undocumented] README does not mention the Capacitor native-app layer (frontend/lib/use-native-app.ts, frontend/lib/auth/native-*.ts) or the Cloudflare/OpenNext deploy files (frontend/open-next.config.ts, frontend/wrangler.jsonc).
