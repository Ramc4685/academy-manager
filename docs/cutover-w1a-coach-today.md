# Cutover Runbook — Wave 1A: Coach Today

**Status:** Authoritative. Run sequentially. Each step has explicit checks.
**Tickets:** W1A-20 (canary + 100%), W1A-21 (legacy parity verification).
**Owners:** RamC + on-call observer.
**Rollback:** Single edge-routing env flip. <60s.

The cutover is what flips real coach traffic from legacy to v2 for the Today
screen. **This is the only step in Wave 1A where production user behavior
changes.** Everything above this point is additive deploy of unused code.

## Pre-flight (≤ 1 day before)

- [ ] Wave 1A exit gate items 1–4 green in staging:
  - [ ] Lighthouse PWA ≥ 90 on `/coach/today`.
  - [ ] LCP < 2.5 s on simulated 4G mobile.
  - [ ] PWA install verified on a real iOS Safari + Android Chrome device.
  - [ ] Golden-master test (`test_coach_today_golden_master.py`) green.
  - [ ] Legacy E2E suite green (no regressions on legacy coach pages).
- [ ] Perf baseline committed to `docs/perf-baseline-coach.md` and
      size-limit / Lighthouse gates flipped to blocking
      (`.github/workflows/v2-frontend.yml`).
- [ ] Observability dashboards live and emitting (W1A-19). Confirm a sample
      request shows up end-to-end.
- [ ] Alert routes verified (SLO breach → PagerDuty or equivalent).
- [ ] V2 backend deployed with `V2_ENABLED=1` and migrations applied
      (`run_pending_migrations`). Hit `/api/v2/healthz` from the production
      origin.
- [ ] V2 frontend deployed to `V2_WEB_ORIGIN` Cloudflare Pages project. Hit
      `/coach/today` against that origin directly — should render (with auth).

## Canary — 10% traffic

Cloudflare splits worker versions by percentage. Push a new version with
`FLAG_COACH_TODAY=v2` and route 10% to it.

```bash
cd edge
# Edit wrangler.toml or use a deploy command that emits a 10% gradual rollout.
wrangler deploy --gradual 10 --env prod
# Or: configure Cloudflare's gradual rollout in the dashboard.
```

**Soak: 1 hour.** Watch:

- p95 `coach.today` latency vs the legacy baseline. **Must stay within 1.5×.**
- Error rate ≤ legacy error rate.
- Install-prompt-shown events firing.
- No `Coaching.*` 5xx (4xx is fine — those are conflict paths).
- Web Vitals: LCP P75 < 2.5 s.

If any check fails for **5 consecutive minutes**, abort:

```bash
# Edit wrangler.toml or via dashboard
wrangler deploy --gradual 0 --env prod
```

Fix root cause, return to pre-flight.

## 100% promotion

After a clean 1h canary:

```bash
wrangler deploy --gradual 100 --env prod
```

Sit on the dashboards for the next **2 hours** with no other deploys.

## Soak — 1 week

- Wave 1B planning **does not start** until 7 calendar days of 100% v2 with
  no rollbacks and SLOs within budget.
- During the soak, all v2 changes touching coach paths require a soak
  review (one extra reviewer on the PR, explicit acknowledgement that
  the soak window remains active).

## Rollback

Any time during canary or soak, one command:

```bash
wrangler secret put FLAG_COACH_TODAY --env prod
# Enter: legacy
```

Propagates globally within ~30 s. Coach traffic returns to legacy.

After rollback:

1. Capture incident in a fresh `docs/incidents/<date>-w1a-rollback.md`.
2. Confirm legacy is healthy (W1A-21 below).
3. Diagnose v2 cause. Patch. New canary attempt requires fresh 1h soak.

## W1A-21 — Legacy parity verification (post-rollback or post-cutover)

Whether we end up on v2 or rolled back to legacy, the legacy stack must
remain healthy for the duration of the migration.

- [ ] `/api/users/me` (legacy) responds 200 for a known coach token.
- [ ] Legacy coach pages reachable via direct URL.
- [ ] Legacy E2E suite green on `main`.
- [ ] No service worker installed on the legacy origin (the SW belongs
      only to `frontend-next`). Confirmed by visiting the legacy origin
      in incognito and checking `chrome://serviceworker-internals/`.

## Sign-off

Wave 1A exit gate item 1 ("Coach Today serves from v2 for 100% of coaches
via edge route") is satisfied **only** when:

- 100% traffic on v2 for ≥ 7 consecutive days.
- No SLO breach during the 7 days.
- No rollback during the 7 days.

Document the date and link to dashboards in the W1A retro.
