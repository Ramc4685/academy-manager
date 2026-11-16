## frontend/README.md

- [wording] README:3,10 say Next.js 15; `frontend/package.json:37` pins `next` 16.4.6 (and `build` uses `next build --webpack`, package.json:7).
- [contract] README:56-58 says the CI workflow reports the size-limit gate with `continue-on-error: true`; `.github/workflows/production.yml` has no size-limit/`pnpm size`/lhci step at all (nothing in `.github/workflows/*.yml` runs it). Budgets exist only at `frontend/package.json:73`.
- [wording] README:28 says no OpenAPI snapshot is committed; `frontend/lib/api/openapi.snapshot.json` and `frontend/lib/api/generated/v2.d.ts` are committed, and CI diffs them (`.github/workflows/production.yml:312-319`). README:88 names `openapi.snapshot.json` without its `lib/api/` path (`package.json:16`).
- [stale-not-built] README:34 lists `components/ui/` (touch-sized primitives); `frontend/components/ui` does not exist (design system lives in `components/ds`).
- [stale-not-built] README:41 lists `public/splash/` iOS splash screens; `frontend/public/splash` does not exist.
- [undocumented] README:21-25 lists four route groups; code also has `(owner)`, `(platform)`, `(shared)`, `(student)` under `frontend/app/`. Admin pages beyond those listed are fine, but README:24 omits parent routes like calendar/attendance/children (minor).
- [undocumented] README:33-37 omits `components/` subdirs actually used (`ds`, `calendar`, `messages`, `pathway`, `persona`, `public-page`, `shared`, `skills`, `teaching`, `waivers`, ...), and README:14 says Firebase "modular `firebase/auth` only" while `frontend/lib/auth` also imports `firebase/app` and `@capacitor-firebase/*` (`frontend/lib/auth/native-push.ts:82`).
- [undocumented] README:80-91 omits scripts `test:unit`, `test:node`, `e2e`, `e2e:local-auth`, `e2e:ui`, `start` (`frontend/package.json:8-21`), which CI uses (`production.yml`).
