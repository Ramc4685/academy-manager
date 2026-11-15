## frontend/README.md

- [stale-not-built] README:56-58 says the size-limit budgets are reported in CI with `continue-on-error: true`. No workflow runs `pnpm size` or `lhci` (grep of `.github/` finds no size-limit or lhci step). Budgets exist only in `frontend/package.json:73-89`, and `.github/workflows/production.yml:277-352` (Frontend Static) has no size step.
- [contract] README:3 and README:10 say Next.js 15, but `frontend/package.json:37` pins `next` 16.4.1. The ADR link also names the old App Router decision.
- [stale-not-built] README:41 lists `public/splash/` (iOS splash screens). The directory does not exist; `frontend/public` has only `favicon.ico`, `icons/` and `manifest.webmanifest`.
- [wording] README:40 says icons are 180/192/256/512/maskable. `frontend/public/icons` has only icon-192, icon-256, icon-512 and icon-maskable, with no 180.
- [stale-not-built] README:34 lists `components/ui/` (touch-sized primitives). It does not exist; the nearest match is `frontend/components/ds`.
- [undocumented] README:21-25 lists four route groups. `frontend/app` also has `(owner)`, `(platform)`, `(student)` and `(shared)`, each with its own `layout.tsx`.
- [undocumented] README:26-32 and README:33-37 omit many `lib/` and `components/` subtrees, for example `lib/admin`, `lib/coach`, `lib/parent`, `lib/tenant`, `lib/observability`, `components/pathway`, `components/waivers` and `components/messages`. Capacitor native auth and push are also missing from README:14: `frontend/lib/auth/native-sign-in.ts:98` and `frontend/lib/auth/native-push.ts:82`.
- [wording] README:14 says `firebase/auth` only. `frontend/lib/auth/firebase.ts:9` imports `firebase/app`.
- [wording] README:84 says `pnpm dev` is plain Turbopack on :3001. `frontend/package.json:6` honors `$PORT`, and `pnpm build` is `next build --webpack` (`package.json:7`), which the README does not mention. Also, `pnpm typecheck` runs `next typegen && tsc --noEmit` (`package.json:13`), not just `tsc --noEmit` (README:86).
