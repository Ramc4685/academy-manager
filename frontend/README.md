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
