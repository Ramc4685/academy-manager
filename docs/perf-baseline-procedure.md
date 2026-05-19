# Performance Baseline Procedure (W1A-01)

**Status:** Required before any size-limit / Lighthouse gate becomes blocking.
**Ticket:** W1A-01
**Output:** `docs/perf-baseline-coach.md` (committed once measured).

The plan (§0.10) is explicit: **CI budgets are informational until baselines exist.** Setting a budget without measuring guarantees either false-fail or false-pass. This document is the recipe.

## When to run this

- Before flipping `size-limit` and `lhci` from `continue-on-error: true` to blocking in `.github/workflows/production.yml`.
- Whenever you add a heavy dependency (e.g., a new icon pack, a chart library).
- During the Wave 1A cutover review (W1A-20 step "pre-flight").

## How to run

You need a local backend running so the coach today route resolves.

```bash
# Terminal 1 — backend
cd backend
V2_ENABLED=1 V2_RUN_MIGRATIONS_ON_BOOT=1 V2_MONGO_URL=mongodb://localhost:27017 \
  V2_DEFAULT_ACADEMY_ID=baseline-academy \
  uvicorn server:app --reload --port 8001

# Seed: insert one coach user, two sessions for today, four enrollments,
# four students into the `baseline-academy` tenant.
python backend/v2/scripts/seed_baseline.py   # see docs/dev-setup.md (Wave 1A polish)

# Terminal 2 — frontend, production build
cd frontend
pnpm install
pnpm build
pnpm start --port 3001 &

# Terminal 3 — measurements
cd frontend
pnpm size > /tmp/size.txt           # bundle weight per route
pnpm lhci collect --url=http://localhost:3001/coach/today  # Lighthouse JSON
```

## Four measurements per route

Run the build four times. Each iteration **adds** the next layer; size-limit
captures only the relevant route group's chunks.

| # | Layer added | What to record |
|---|---|---|
| 1 | Empty coach shell — `app/(coach)/layout.tsx` + bottom nav, no data | Initial JS gz for `(coach)/today` |
| 2 | + Firebase Auth (`firebase/auth` modular imports) | Initial JS gz |
| 3 | + TanStack Query + `lib/api/coach.ts` | Initial JS gz |
| 4 | + Today screen with real data fetch | Initial JS gz, LCP (4G simulated), TTI, Lighthouse PWA score |

Per the plan, **CI budget = measured + 15%**, with the stretch target documented separately. Record both in `docs/perf-baseline-coach.md`.

## Template for `docs/perf-baseline-coach.md`

```markdown
# Coach Today — perf baseline

**Date:** YYYY-MM-DD
**Commit SHA:** <sha>
**Hardware:** GitHub Actions ubuntu-latest (for repeatability), measured locally on <CPU> for sanity.

## Measurements

| Layer | Initial JS gz | LCP | TTI | Lighthouse PWA |
|---|---|---|---|---|
| 1. Empty shell | __ KB | — | — | — |
| 2. + Firebase Auth | __ KB | — | — | — |
| 3. + TanStack Query + BFF client | __ KB | — | — | — |
| 4. + Today screen | __ KB | __ s | __ s | __ |

## Budgets (= measured + 15%)

| Route | size-limit | Lighthouse perf | Lighthouse PWA |
|---|---|---|---|
| `(coach)/today` | __ KB | ≥ 90 | ≥ 90 |

## Stretch targets

| Route | size-limit | Lighthouse perf |
|---|---|---|
| `(coach)/today` | __ KB | ≥ 95 |
```

## Flipping CI gates from informational → blocking

After the baseline lands and the budgets are populated in
`frontend/package.json`:

1. Edit `.github/workflows/production.yml`:
   - Remove `continue-on-error: true` from the `Size limit` step.
   - Remove `continue-on-error: true` from the `Lighthouse CI` step.
2. Open a PR; the workflow runs against the same commit and confirms the
   budgets are headroomed.
3. Merge.

## Anti-patterns

- ❌ Setting a budget by guessing ("100 KB sounds tight"). The plan's
  120 KB-ish number is a *target*, not a baseline.
- ❌ Measuring on a fresh laptop with no other windows. Variance is high.
- ❌ Measuring on dev server. Always production build.
- ❌ Updating the baseline silently in a feature PR. Baseline changes
  warrant their own PR with a CHANGES section explaining the diff.
