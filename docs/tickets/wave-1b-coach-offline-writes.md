# Wave 1B — Coach Offline Attendance Writes

**Goal:** Coach can mark attendance offline. Mutations queue locally, sync on reconnect, conflict outcomes surface in a "Needs review" tray. Six §0.9 conflict cases enforced server-side, tested end-to-end.

**Prerequisite:** Wave 1A holds 1 week in production with no rollback (per architect rule #3).

**Exit gate (from plan):**
1. Each §0.9 conflict case has an automated test and documented UX outcome.
2. 48h soak with synthetic offline coaches produces zero phantom marks.
3. No regression to 1A bundle budget.

**Estimate:** ~1.5 weeks.

---

## Tickets

### W1B-01 — IndexedDB mutation queue
- **Type:** Frontend / Infra
- **Estimate:** 6h
- `lib/offline/queue.ts`. Append-only queue keyed by mutation ULID. Survives reload + browser restart.
- **Acceptance:** Unit-test the queue add/list/drain/remove ops via a fake IndexedDB.

### W1B-02 — Sync orchestrator
- **Type:** Frontend / Infra
- **Estimate:** 5h
- `lib/offline/sync.ts`. Serial per device. Backoff 1/4/16/60s capped on 5xx. 4xx routes to tray. Idempotent: replays return original result.
- **Acceptance:** Vitest covers transient retry, conflict-to-tray, banner after 5 attempts.

### W1B-03 — "Needs review" tray UI
- **Type:** Frontend / UI
- **Estimate:** 5h
- `app/(coach)/needs-review/page.tsx` + `components/coach/tray-row.tsx`. Lists failed mutations with reason; offers dismiss / export / device-pick (case #4).
- **Acceptance:** Each conflict case renders a distinct UX outcome per [docs/offline-policy.md](../offline-policy.md).

### W1B-04 — Offline write enablement on session detail
- **Type:** Frontend / UI
- **Estimate:** 2h
- Replace W1A's "You're offline" disabled state with queue-on-offline behavior. Toggles still surface optimistic UI; on reconnect, sync runs.
- **Acceptance:** Manual test: airplane → toggle → reconnect → mark appears server-side.

### W1B-05 — Service-worker Background Sync registration
- **Type:** Frontend / Infra
- **Estimate:** 4h
- Replace W1A's `NetworkOnly` for `POST /attendance` with a `BackgroundSyncPlugin`-backed strategy when the browser supports it; otherwise fall through to the JS-driven orchestrator (W1B-02).
- **Acceptance:** Manual: queued POST under iOS Safari (no BG sync) replays via JS orchestrator; Android Chrome uses BG sync queue.

### W1B-06 — Coach-side audit log of rejected/dismissed marks
- **Type:** Frontend / Infra
- **Estimate:** 2h
- IndexedDB collection `coach_audit` retaining rejected and dismissed mutations 30d, exportable as CSV.
- **Acceptance:** Tray "export" produces the expected CSV.

### W1B-07 — Server-side double-mark race protection
- **Type:** Backend / Test
- **Estimate:** 2h
- Verify the `(academy_id, session_id, student_id)` unique index returns the second writer's `ConflictAttendanceExists`. Add a contract test reproducing the race via Mongo `insertMany`.
- **Acceptance:** Contract test reproduces case #4 with deterministic loser.

### W1B-08 — Playwright E2E for all six §0.9 conflict cases
- **Type:** Test / E2E
- **Estimate:** 6h
- One spec per case:
  - same student marked twice offline → one mutation queued
  - session cancelled while offline → tray with "session cancelled"
  - student removed from roster while offline → tray with "not enrolled"
  - two-device same student → server first wins, second to tray
  - wrong session_id → tray with "not assigned"
  - payment status change → not surfaced (case #6 is "no-op for coach UI")
- **Acceptance:** All 6 specs green in CI on Pixel 7 + iPhone 14 Playwright projects.

### W1B-09 — Per-coach feature flag for safe rollout
- **Type:** Backend
- **Estimate:** 2h
- `FLAG_W1B_OFFLINE_WRITES` env-flag in coach route group; when disabled the route group reverts to W1A behavior. Allows soak on a single coach pilot.
- **Acceptance:** Flag flip reverts behavior verifiably.

### W1B-10 — 48h synthetic-offline soak script
- **Type:** Ops
- **Estimate:** 3h
- `scripts/soak-coach-offline.ts` — Playwright headless loop simulating offline coaches marking attendance; asserts zero phantom marks.
- **Acceptance:** Soak runs in staging for 48h with zero divergence.

## Exit Checklist

- [ ] W1B-01 … W1B-09 merged.
- [ ] W1B-10 soak passed in staging.
- [ ] No regression in Wave 1A bundle budget.
- [ ] [docs/offline-policy.md](../offline-policy.md) coverage table fully checked.
- [ ] 1-week soak in production (canary first per per-coach flag W1B-09) before Wave 2 opens.
