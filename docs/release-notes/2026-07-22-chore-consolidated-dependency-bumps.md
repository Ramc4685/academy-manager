# chore-consolidated-dependency-bumps

PR: #326

Consolidates the eleven open Dependabot PRs (#267, #271–#280) into a single
change. Three of them could not go green individually — they only resolve when
the bumps land together.

## What changed

**Backend (`backend/requirements.txt`)**
- `ast_serialize` 0.3.0 → 0.6.0 (#274)
- `botocore` 1.43.33 → 1.43.40 (#275)
- `openai` 1.99.9 → 2.44.0 (#271) — major bump, but no application code
  imports `openai`; it is a transitive-only pin.
- `typer` 0.25.1 → 0.26.8 (#272)
- `huggingface_hub` 1.17.0 → 1.24.0 (#273 asked for 1.21.0 — see below)
- `hf-xet` 1.5.0 → 1.5.2 (not a Dependabot PR; required by the hub bump)
- `click` 8.4.1 → 8.4.2 (not a Dependabot PR; required by the hub bump)

Why the hub goes past 1.21.0: `huggingface_hub` 1.21.0 pins `typer<0.26.0`, so
#272 and #273 are mutually unsatisfiable at that version — that is exactly why
both were red. Hub 1.24.0 drops the `typer` constraint entirely, which lets both
land. It also requires `hf-xet>=1.5.1` and `click>=8.4.2`, hence those two extra
pins. No application code imports `huggingface_hub` or `typer` (they are
transitive), so the wider jump carries no call-site risk.

**Frontend (`frontend/package.json`)**
- `@radix-ui/react-dialog` 1.1.16 → 1.1.18 (#276)
- `@tanstack/query-sync-storage-persister` 5.101.0 → 5.101.2 (#277)
- `@tanstack/react-query` 5.59.16 → 5.101.2 (#278)
- `@tanstack/react-query-persist-client` 5.59.16 → 5.101.2 (not a Dependabot
  PR; required to fix #278)
- `firebase` 11.0.2 → 12.15.0 (#280) — major bump
- `recharts` 3.8.1 → 3.9.1 (#279)

Why the extra TanStack package: #278 failed `tsc` with a `QueryClient` type
mismatch in `lib/query/persistence.ts` because `react-query` moved to 5.101.2
while `react-query-persist-client` stayed at 5.59.16, dragging in a second copy
of `@tanstack/query-core`. Bumping the whole TanStack family to one version
collapses it back to a single `query-core` and the type error disappears.

**pnpm (`frontend/pnpm-workspace.yaml`)**
firebase 12.x adds a postinstall script in `@firebase/util`, which pnpm blocks
pending an explicit decision. It is recorded as `allowBuilds: false`: the script
only writes a config file when `FIREBASE_WEBAPP_CONFIG` is set (Firebase App
Hosting auto-init), and this project configures Firebase through `NEXT_PUBLIC_*`
env vars and never sets that variable, so the script is a guaranteed no-op here.

**CI (`.github/workflows/`)**
`actions/checkout` v6 → v7 across `production.yml` and `release-notes.yml`
(#267). The one SHA-pinned usage is repinned to
`3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1).

## Verification
Run locally against the bumped packages, all green:
- `pytest v2/tests` — 2553 passed
- `ruff check v2`, `ruff format --check v2` — clean
- `lint-imports` — 5 contracts kept, 0 broken
- `mypy` + `mypy-baseline filter` — no new errors
- `pnpm typecheck` — clean (this is the check #278 failed)
- `pnpm lint` — 0 errors (6 pre-existing warnings)
- `pnpm build` — production build succeeds through the firebase 12 major

## Deploy notes
No migrations, no env changes, no config changes. Backend and frontend both
need a redeploy to pick up the new dependency sets.

## Risk / rollback
Moderate — two major bumps (`firebase` 11→12, `openai` 1→2). `openai` is
transitive-only with no import sites, so its risk is effectively nil. `firebase`
12 is exercised by the auth/storage paths; typecheck and production build both
pass, but auth login and file upload are worth a smoke test after deploy.
Rollback is `git revert` of the single commit plus a redeploy.
