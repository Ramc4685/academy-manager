# frontend

Next.js 15 App Router PWA for Academy Manager. See [ADR-0002](../docs/adr/0002-nextjs-app-router.md).

This is the only frontend app in the repository. The old CRA app was removed
after production cutover.

## Stack

- Next.js 15 (App Router, RSC for admin, client components for coach/parent)
- React 19, TypeScript strict
- Tailwind + Radix + shadcn-style primitives
- TanStack Query (with persistence for coach offline reads)
- Firebase Web SDK (modular `firebase/auth` only)
- Serwist (Workbox successor) for service worker
- ULID for client mutation IDs

## Layout

```
app/
├── (marketing)/         # public landing, login
├── (coach)/             # coach dashboard, today, sessions, teaching-plan flows
├── (parent)/            # parent dashboard, onboarding, payments, progress, waivers
└── (admin)/             # admin control plane, billing, users, sessions, reports
lib/
├── api/                 # base client + per-persona typed clients
│   └── generated/       # reserved for generated OpenAPI types; currently no snapshot is committed
├── auth/                # modular Firebase auth
├── pwa/                 # install prompt, update flow, offline indicator
├── offline/             # IndexedDB mutation queue and sync helpers
└── query/               # TanStack Query setup + keys
components/
├── ui/                  # touch-sized primitives
├── coach/               # coach-only, dynamically imported
├── parent/
└── admin/
public/
├── manifest.webmanifest
├── icons/               # 180/192/256/512/maskable
└── splash/              # iOS splash screens
```

## Persona route groups

Each persona is a [route group](https://nextjs.org/docs/app/building-your-application/routing/route-groups). The folder name in parens does not appear in URLs:

- `app/(coach)/coach/today/page.tsx` → `/coach/today`
- `app/(parent)/parent/onboarding/page.tsx` → `/parent/onboarding`
- `app/(admin)/admin/sessions/page.tsx` → `/admin/sessions`

Each group has its own `layout.tsx` so the coach shell (bottom nav, no calendar lib) is fully separate from the admin shell (sidebar, calendar dynamic-imported).

## Bundle budgets

Set in `package.json` under `size-limit` for the coach Today, parent onboarding,
and admin landing chunks. The CI workflow reports this gate with
`continue-on-error: true`.

## Dependency vulnerability scan

CI runs `pnpm audit --audit-level=high` (Frontend Static job) before typecheck,
lint, and build. The gate stays at `high` — do not lower the level or skip the
step.

Suppressions live in `pnpm-workspace.yaml` under `auditConfig.ignoreGhsas`
(pnpm 11 no longer reads a `pnpm` field in `package.json`). Almost every entry
there is paired with a patched `overrides` pin — the ignore exists only because
`pnpm audit` still evaluates the upstream declared range.

The one exception is **GHSA-jmr9-qjv8-65gv** (`extract-zip <=2.0.1`,
unvalidated symlink path traversal), which has no patched release to pin to.
It is reached only transitively through **devDependencies** (`@lhci/cli` →
lighthouse → puppeteer-core → `@puppeteer/browsers`, and `size-limit` → estimo
→ find-chrome-bin → `@puppeteer/browsers`), so it never ships in the deployed
bundle. The advisory names `>=2.0.2` as patched, but no such version has been
published — `extract-zip@2.0.1` is still the latest release. Remove the entry
once upstream publishes a fix or the puppeteer chain drops `extract-zip`.

## Scripts

```bash
cp .env.example .env.local
pnpm dev          # next dev on :3001
pnpm build        # production build
pnpm typecheck    # tsc --noEmit
pnpm lint
pnpm generate:api # generate lib/api/generated/v2.d.ts from a running local v2 OpenAPI
pnpm size         # size-limit check
pnpm lhci         # Lighthouse CI run
```
