## frontend/README.md

- [wording] README:3,10 say "Next.js 15"; `frontend/package.json:37` pins `next` 16.4.6 (build uses `next build --webpack`, package.json:7).
- [stale-not-built] README:34-35 `components/ui/` (touch-sized primitives) does not exist; primitives live in `frontend/components/ds/` (e.g. `components/ds/button.tsx`).
- [stale-not-built] README:41 `public/splash/` (iOS splash screens) does not exist; `frontend/public/` has only `favicon.ico`, `icons/`, `manifest.webmanifest`.
- [stale-not-built] README:56-58 bundle budgets are said to be reported by CI with `continue-on-error: true`; no workflow under `.github/workflows` (e.g. `production.yml:295-325` Frontend Static job) runs `pnpm size` or `lhci`. Budgets exist only in `frontend/package.json:73-89` (360 KB each).
- [undocumented] README:20-25 lists four route groups; `frontend/app/` also has `(owner)`, `(platform)`, `(shared)` and `(student)` groups, each with its own `layout.tsx`.
- [undocumented] README:26-32 `lib/` omits many modules: `lib/admin`, `lib/coach`, `lib/parent`, `lib/tenant`, `lib/observability`, `lib/ui`, `lib/format` and others (e.g. `frontend/lib/providers.tsx`). `components/` also has `ds`, `pathway`, `skills`, `teaching`, `waivers` and more beyond the four documented folders.
- [wording] README:28 says `lib/api/generated/` has "currently no snapshot is committed"; `frontend/lib/api/generated/v2.d.ts` and `frontend/lib/api/openapi.snapshot.json` are both committed, and CI diffs them (`production.yml:312-320`). README:88 gives the snapshot path as bare `openapi.snapshot.json`; the real path is `lib/api/openapi.snapshot.json` (package.json:16).
- [contract] README:62-64 says the audit gate runs `pnpm audit --audit-level=high` directly; CI wraps it in `scripts/ci/dependency_audit.sh` (`production.yml:310`), which downgrades a registry outage to a warning.
