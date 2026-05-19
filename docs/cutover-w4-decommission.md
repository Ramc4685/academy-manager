# Cutover Runbook — Wave 4: Decommission

**Tickets:** W4-01 … W4-12.
**Pre-requisites:** Waves 1A, 1B, 2, 3 each holding for 7+ days in production with no rollback.

This wave is **two-step with a 30-day window**:
- **4A — Disable (Day 0):** route legacy traffic away, return 410s, gate legacy frontend behind admin-only `/legacy/*`, drop a freeze marker.
- **4B — Delete (Day 30+):** remove legacy code, promote v2 to canonical paths, simplify CI + edge.

---

## Step 4A — Day 0 (Disable)

### 1. Final pre-flight

- [ ] Every persona's exit gate cleared and held for 7 days.
- [ ] Last week's audit shows zero legacy `/api/*` calls from real users (other than `/healthz`-style polling) — verifiable from Cloudflare analytics.
- [ ] Outbox + dead-letter clean.
- [ ] Stripe webhook fully routed to v2 endpoint; legacy webhook endpoint removed from Stripe dashboard (per Wave 2 cutover).

### 2. Disable legacy at the edge

```bash
cd edge
# Open the admin-only escape hatch (so an emergency rollback can reach legacy)
wrangler secret put FLAG_LEGACY_HATCH_OPEN --env prod   # value: 1
# Turn off legacy /api/*
wrangler secret put FLAG_LEGACY_API_GONE  --env prod   # value: 1
```

After ~30 s propagation:
- All `/api/*` returns 410.
- `/legacy/*` is the only path that still reaches the legacy origin.
- `/api/v2/*` unaffected.

### 3. Disable legacy CI workflows

Open a PR that sets the legacy CI workflows to `workflow_dispatch` only — so they can still be run manually for an emergency rollback build, but no longer run on push.

```yaml
# .github/workflows/ci.yml + deploy.yml
on:
  workflow_dispatch: {}   # only manual triggers during the quiet window
```

### 4. Drop the freeze marker

```bash
cp docs/LEGACY-FREEZE-TEMPLATE.md LEGACY-FREEZE-$(date +%Y-%m-%d).md
# Fill in the placeholders (frozen date, SHAs, window end). Commit + push.
```

### 5. Observe the quiet window

- **Day 7 check** — marker review. Confirm no rollback. Update marker.
- **Day 14 check** — same.
- **Day 30 check** — same. Sign off in marker. Proceed to 4B.

If at any point a rollback is needed:

```bash
wrangler secret put FLAG_<persona>_ALL --env prod   # value: legacy
wrangler secret put FLAG_LEGACY_API_GONE --env prod # value: 0
```

…and re-set the marker's "Frozen date" to today (the 30-day clock restarts).

---

## Step 4B — Day 30+ (Delete)

Done as a sequence of small PRs so review is tractable. **Each PR builds on the previous.** Merge them in order; the build stays green throughout.

### PR 1: Delete legacy backend modules

- Remove `backend/routers/`, `backend/services/`, `backend/models.py`, `backend/auth.py` (legacy file — the v2 auth is under `backend/v2/shared/auth/`), `backend/tests/`.
- Update `backend/server.py` to be a single-line launcher that just imports `backend.v2.main:app`.
- Verify `pytest backend/v2/tests/` still passes.

### PR 2: Promote `backend/v2/` → `backend/`

- `git mv backend/v2/* backend/`
- Update imports across the whole tree (`backend.v2.` → `backend.`).
- Update `backend/pyproject.toml` `import-linter` source modules (`backend.v2.*` → `backend.*`).
- Update CI workflow path filters.
- Verify a full backend test + lint run is green.

### PR 3: Delete legacy frontend (completed)

- Legacy CRA source has been removed from `frontend/`.
- Cloudflare Pages `courtmastr-academy` is unbound/deleted by the production workflow if it still exists.

### PR 4: Promote frontend to canonical path (completed)

- `frontend/` is now the canonical Next.js app.
- GitHub Actions deploys `frontend/` to the `academy-next` Cloudflare Worker.

### PR 5: Simplify edge worker

- Remove `LEGACY_API_ORIGIN`, `LEGACY_WEB_ORIGIN` from `edge/wrangler.toml`.
- Drop the legacy-routing decisions from `edge/router.ts` — worker reduces to "anything `/api/v2/*` → v2 API, anything else → v2 web."
- Drop `FLAG_*` env vars that are no longer needed.
- Worker test suite updated to reflect the simplified table.

### PR 6: Single CI pipeline

- Rename `.github/workflows/v2-backend.yml` → `backend.yml`.
- Rename `.github/workflows/v2-frontend.yml` → `frontend.yml`.
- Rename `.github/workflows/v2-edge.yml` → `edge.yml`.
- Delete `.github/workflows/ci.yml` and `deploy.yml` (legacy workflows).
- All path filters point at the canonical paths (no more `v2-` prefix).

### PR 7: Docs sweep

- Run a search for `v2` in `docs/` and drop the qualifier where it's no longer meaningful.
- Update ADRs with "Status: Accepted" → review whether any deserve "Superseded by …". Most stay Accepted; they describe load-bearing decisions still in force.
- Delete the freeze marker file.
- Commit the retro (see below).

---

## Retro

After PR 7 merges, commit `docs/retros/decommission.md` from
[docs/retros/decommission-template.md](retros/decommission-template.md).
Cover:

- What worked: vertical-slice waves, per-flag edge cutover, the 30-day window.
- What was hard.
- What we'd change for the next major migration.

This closes Wave 4.
