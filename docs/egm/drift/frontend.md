## frontend/README.md

- [wording] README:3, README:10 say "Next.js 15"; `frontend/package.json:37` pins `next` 16.4.6 (build is `next build --webpack`, `package.json:7`). ADR-0002 also says 15.
- [stale-not-built] README:57-58 says the CI workflow reports the size-limit gate with `continue-on-error: true`; no workflow under `.github/` runs `pnpm size` or `lhci` (`.github/workflows/production.yml` Frontend Static job, ~line 277-340, has no such step). Config exists only at `frontend/package.json:73-89`.
- [wording] README:28 says `lib/api/generated` has "no snapshot is committed"; `frontend/lib/api/generated/v2.d.ts` and `frontend/lib/api/openapi.snapshot.json` are both committed, and CI diffs them (`.github/workflows/production.yml:312-319`). README:88 itself says regeneration is from the committed snapshot.
- [missing] README:34 lists `components/ui/` (touch-sized primitives); the directory does not exist. Primitives live in `frontend/components/ds/` (e.g. `button.tsx`, `dialog-chrome.tsx`).
- [stale-not-built] README:41 lists `public/splash/` (iOS splash screens); `frontend/public/splash` does not exist.
- [wording] README:40 says icons include 180; `frontend/public/icons/` has only 192/256/512/maskable (`public/icons/README.md:8` mentions `icon-180.png`, also absent).
- [undocumented] README:21-25 lists four route groups; `frontend/app/` also has `(owner)`, `(platform)`, `(shared)`, `(student)` groups, each with its own `layout.tsx`, plus `app/api`.
- [wording] README:22 puts landing in `(marketing)`; the landing page is `frontend/app/page.tsx` (marketing group holds login, register, legal pages).
- [undocumented] README:35-37 omit many `frontend/components/*` dirs (`ds`, `shared`, `calendar`, `messages`, `pathway`, `skills`, `teaching`, `waivers`, and others); `frontend/lib` also has `admin`, `coach`, `design`, `format`, `navigation`, `observability`, `parent` (README:26-32 lists five).
- [wording] README:84 says `pnpm dev` is "Turbopack on :3001"; `package.json:6` uses `--turbopack -p ${PORT:-3001}`, so the port is overridable.
