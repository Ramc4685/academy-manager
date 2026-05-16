# Decommission Retro — Template

> **Step W4-12.** Copy to `docs/retros/decommission.md` after Wave 4B PRs merge.

**Date:** YYYY-MM-DD
**Authors:** `<names>`

## Timeline (actual vs plan)

| Wave | Estimated | Actual | Notes |
|---|---|---|---|
| Phase 0 | 1w | | |
| Wave 1A | 2w | | |
| Wave 1B | 1.5w | | |
| Wave 2 | 3w | | |
| Wave 3 | 3–4w | | |
| Wave 4A | 1d (+30d soak) | | |
| Wave 4B | 1w | | |

## What worked

- (e.g. vertical-slice waves caught BFF mismatches early at low cost)
- (e.g. per-flag edge cutover let us roll back in <30s)
- (e.g. golden-master tests caught two contract drifts)

## What was hard

- (e.g. RSC server/client boundary tripped us up in Wave 3 — calendar wouldn't render)
- (e.g. tenant-scope leak we missed until contract tests)

## What we'd change

- (e.g. baseline perf earlier — we set the budget after Wave 1A baseline measurement which delayed the size-limit gate by a week)
- (e.g. Stripe webhook fixture replay would have been easier as the first task of Wave 2 rather than near the end)

## Load-bearing decisions still in force

Re-read each ADR. Note any whose context has shifted enough that they merit a
fresh ADR.

- [ ] [ADR-0001 FastAPI + Mongo](../adr/0001-fastapi-mongodb-stays.md) — still right?
- [ ] [ADR-0002 Next.js App Router](../adr/0002-nextjs-app-router.md) — still right?
- [ ] [ADR-0003 BFF inside backend](../adr/0003-bff-inside-backend.md) — has any lift-out trigger fired?
- [ ] [ADR-0004 PWA over native](../adr/0004-pwa-over-native.md) — has any Capacitor promotion trigger fired?
- [ ] [ADR-0005 Clean-arch-lite monolith](../adr/0005-clean-architecture-lite-monolith.md) — any context need promotion?
- [ ] [ADR-0006 Tenant-ready single-tenant](../adr/0006-tenant-ready-single-tenant-shipped.md) — multi-tenant decision deferred? Or due?

## Follow-up tasks

- [ ] (e.g. delete `# FINANCE` markers and promote Finance to its own context if its rules diverged)
- [ ] (e.g. promote Onboarding to a context if waivers grew their own lifecycle)
- [ ] (e.g. revisit perf budgets after 90 days of real-user data)
