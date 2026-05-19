# Wave 4 — Decommission

**Goal:** Disable legacy stack behind a 30-day quiet window; after 30 days, delete legacy code and lift v2 to the canonical `backend/` and `frontend/` paths.

**Prerequisite:** Waves 1A, 1B, 2, 3 all running on v2 in production with no rollbacks for the past 7 days.

**Per ADR / plan rule #4:** legacy code is disabled before deletion. 30-day quiet window mandatory.

**Estimate:** ~1 week of work + 30-day soak.

---

## Step 4A — Disable legacy (Day 0)

### W4-01 — Edge routing returns 410 Gone for legacy `/api/*`
- **Type:** Ops / Edge
- **Estimate:** 2h
- Set `FLAG_LEGACY_API_GONE=1` in `edge/wrangler.toml`. `edge/router.test.ts` already asserts this.

### W4-02 — Legacy frontend gated to `/legacy/*` admin-only
- **Type:** Ops / Edge + Backend
- **Estimate:** 3h
- Edge worker routes `/legacy/*` to legacy CRA; backend adds an admin-only auth check on the legacy `/api/*` (now unused but reachable through `/legacy/`). This is the rollback safety net.

### W4-03 — `LEGACY-FREEZE-<date>.md` marker file at repo root
- **Type:** Doc
- **Estimate:** 0.5h
- Records the date, the team, and the rollback recipe. Reviewed monthly during the soak.

### W4-04 — Disable legacy CI workflows
- **Type:** Ops / CI
- **Estimate:** 1h
- `.github/workflows/ci.yml` and `deploy.yml` (legacy) move to `workflow_dispatch` only. v2-* workflows become canonical.

## Step 4B — Delete (Day 30+)

### W4-05 — Delete legacy backend
- **Type:** Code removal
- **Estimate:** 2h
- Remove `backend/routers/`, `backend/services/`, `backend/models.py`, `backend/db.py`, `backend/auth.py` (legacy), `backend/tests/`. Update `backend/server.py` to be a tiny v2 launcher (or remove entirely once v2 is the canonical app).

### W4-06 — Promote v2 → canonical
- **Type:** Code
- **Estimate:** 4h
- Move `backend/v2/` → `backend/`. Update imports across the codebase (`backend.v2.*` → `backend.*`). Update import-linter rules.

### W4-07 — Delete legacy frontend
- **Type:** Code removal
- **Estimate:** 2h
- Completed by promoting the Next.js app into `frontend/` and removing the old CRA source.

### W4-08 — Promote frontend → canonical
- **Type:** Code
- **Estimate:** 3h
- `frontend/` is the canonical Next.js app. Deployment targets the `academy-next` Cloudflare Worker.

### W4-09 — Single CI pipeline
- **Type:** Ops / CI
- **Estimate:** 2h
- Delete legacy workflows. Rename `v2-backend.yml` → `backend.yml`, `v2-frontend.yml` → `frontend.yml`.

### W4-10 — Edge routing simplification
- **Type:** Ops / Edge
- **Estimate:** 2h
- Remove legacy origins and per-persona flags from `edge/wrangler.toml` and `edge/router.ts`. Worker becomes a thin passthrough or is retired entirely if Cloudflare Pages handles routing natively.

### W4-11 — Final docs sweep
- **Type:** Doc
- **Estimate:** 4h
- Update all docs/ that say "v2" to drop the qualifier. Update ADR-0001 … ADR-0006 status with a `Superseded by` line only where actually superseded.

### W4-12 — Post-decommission retro
- **Type:** Doc
- **Estimate:** 2h
- `docs/retros/decommission.md`. What went right, what was hard, recommendations for the next major migration.

## Exit Checklist

- [ ] 4A: legacy disabled, marker in place, rollback recipe tested by a dry-run revert.
- [ ] 30-day quiet window observed. No rollback. Marker file reviewed at days 7, 14, 30.
- [ ] 4B: legacy code removed; v2 promoted to canonical paths; single CI; edge config simplified.
- [ ] Retro committed.
