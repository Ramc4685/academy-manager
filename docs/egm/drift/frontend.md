## frontend/README.md

- [stale-not-built] README.md:58 says CI reports the size-limit gate with `continue-on-error: true`; no workflow in `.github/workflows/*.yml` runs `pnpm size` (or `lhci`). Only the `size-limit` config exists at `frontend/package.json:73-90`.
- [stale-not-built] README.md:28 says no generated snapshot is committed under `lib/api/generated/`, but `frontend/lib/api/generated/v2.d.ts` and `frontend/lib/api/openapi.snapshot.json` are both committed. `frontend/lib/api/README.md:13-14` repeats the old claim.
- [contract] README.md:3, :10 say Next.js 15, but `frontend/package.json:37` pins `next` 16.4.6. The build uses `next build --webpack` (`package.json:7`) and the dev script uses `--turbopack` (`package.json:6`).
- [stale-not-built] README.md:40-41 lists `public/icons/` as 180/192/256/512/maskable and `public/splash/` for iOS splash screens. `frontend/public/icons/` has only 192, 256, 512 and maskable, with no 180 icon. `frontend/public/splash/` does not exist.
- [missing] README.md:34 lists `components/ui/` (touch-sized primitives), but `frontend/components/ui` does not exist. `components/ds/` is the nearest match.
- [undocumented] README.md:21-25 documents four route groups. `frontend/app/` also has `(owner)`, `(platform)`, `(student)` and `(shared)`, each with its own `layout.tsx`.
- [undocumented] README.md:20-42 omits several top-level code areas: `frontend/middleware.ts`, `frontend/e2e/`, `frontend/app/sw.ts` (the Serwist worker), `frontend/open-next.config.ts` and `wrangler.jsonc` (Cloudflare/OpenNext deploy), and the `lib/admin`, `lib/coach`, `lib/parent` and `lib/design` folders. It also omits `components/` subfolders such as `calendar`, `ds`, `teaching`, `pathway` and others.
- [wording] README.md:52 says the admin shell has the calendar dynamic-imported. The dynamic import is in `frontend/app/(admin)/admin/sessions/page.tsx:45`, not in `frontend/app/(admin)/layout.tsx`.
- [wording] README.md:14 says Firebase `firebase/auth` only. `frontend/lib/auth/firebase.ts` also imports `firebase/app`.
- [wording] README.md:12 lists Tailwind + Radix. `frontend/package.json:27-28` has only `@radix-ui/react-dialog` and `react-slot`. Tailwind is v4 (`package.json:68`).
- [wording] README.md:86 says `pnpm typecheck` is `tsc --noEmit`. It is actually `next typegen && tsc --noEmit` (`frontend/package.json:13`).
- [wording] README.md:88 says `pnpm generate:api` regenerates `lib/api/generated/v2.d.ts` from the committed snapshot. This matches `package.json:16`, but contradicts README.md:28.
