## frontend/README.md

- [wording] README:3,10 say "Next.js 15"; `frontend/package.json:37` pins `next` 16.4.6.
- [wording] README:14 says "modular `firebase/auth` only"; `frontend/lib/auth/firebase.ts` also imports `firebase/app`.
- [stale-not-built] README:28 says no OpenAPI snapshot is committed under `lib/api/generated`; `frontend/lib/api/generated/v2.d.ts` and `frontend/lib/api/openapi.snapshot.json` are committed, and `.github/workflows/production.yml:312` (OpenAPI drift check) enforces them. README:88 correctly describes the snapshot, so the two lines contradict each other.
- [stale-not-built] README:34 lists `components/ui/` (touch-sized primitives); the directory does not exist. Primitives live in `frontend/components/ds/` (`ds/index.ts`).
- [stale-not-built] README:41 lists `public/splash/` (iOS splash screens); `frontend/public/splash` does not exist (`frontend/public` has only `favicon.ico`, `icons/`, `manifest.webmanifest`).
- [stale-not-built] README:54-58 says CI reports the size-limit gate with `continue-on-error: true`; no workflow under `.github/` runs `pnpm size` or `lhci` (see `.github/workflows/production.yml` frontend job). The `size-limit` config exists at `frontend/package.json:73-92`, with a 360 KB limit on each of the three chunks.
- [undocumented] README:21-25 lists four route groups; `frontend/app/` also has `(owner)`, `(platform)`, `(student)` and `(shared)`, each with its own `layout.tsx`.
- [undocumented] README:33-37 lists `components/ui|coach|parent|admin`; `frontend/components/` also has `ds`, `calendar`, `public-page`, `marketing`, `messages`, `pathway`, `persona`, `progress`, `skills`, `teaching`, `waivers`, `announcements`, `observability` and `shared`.
- [undocumented] README:26-32 lists five `lib/` subfolders; `frontend/lib/` also has `admin`, `coach`, `parent`, `design`, `format`, `navigation`, `observability`, `public-page`, `tenant`, `time`, `ui` and `waivers`, plus many top-level modules.

Re-checked 2026-11-16 against the coach-attendance change (fix/coach-attendance): no new drift; items above still hold.
