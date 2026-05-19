# frontend

Next.js 15 App Router PWA for academy-manager v2. See [ADR-0002](../docs/adr/0002-nextjs-app-router.md).

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
├── (coach)/             # Wave 1A target — mobile-first, bottom-tab nav
├── (parent)/            # Wave 2
└── (admin)/             # Wave 3
lib/
├── api/                 # base client + per-persona typed clients
│   └── generated/       # openapi-typescript output, committed
├── auth/                # modular Firebase auth
├── pwa/                 # install prompt, update flow, offline indicator
├── offline/             # IndexedDB mutation queue (Wave 1B only)
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

Set in `package.json` under `size-limit`. Phase 0 budgets are placeholders;
real values land per wave after baseline measurement (W1A-01).

## Scripts

```bash
cp .env.example .env.local
pnpm dev          # next dev on :3001
pnpm build        # production build
pnpm typecheck    # tsc --noEmit
pnpm lint
pnpm generate:api # regenerate lib/api/generated/v2.d.ts from the local v2 OpenAPI
pnpm size         # size-limit check
pnpm lhci         # Lighthouse CI run
```
