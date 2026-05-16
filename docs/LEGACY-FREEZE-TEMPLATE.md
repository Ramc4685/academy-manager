# LEGACY-FREEZE-`<YYYY-MM-DD>`

> **Step W4-03.** When Wave 4A starts, copy this template to the repo root as
> `LEGACY-FREEZE-<date>.md` and fill in the placeholders. The marker is
> reviewed at days 7, 14, and 30 of the quiet window.

**Frozen date:** YYYY-MM-DD
**Frozen by:** `<name>`
**Quiet window ends:** YYYY-MM-DD (+30 days)
**Removal PR target date:** YYYY-MM-DD

## State at freeze

- All persona traffic routes to v2:
  - `FLAG_COACH_ALL=v2`
  - `FLAG_PARENT_ALL=v2`
  - `FLAG_ADMIN_ALL=v2`
- `FLAG_LEGACY_API_GONE=1` — legacy `/api/*` returns 410.
- `FLAG_LEGACY_HATCH_OPEN=1` — `/legacy/*` reachable as admin-only escape hatch.
- Last v2 deploy SHA: `<sha>`
- Last legacy code SHA in `main`: `<sha>` (will be deleted in Wave 4B).

## Rollback recipe

If a critical regression is found during the quiet window:

```bash
# 1. Flip the affected persona back to legacy.
wrangler secret put FLAG_<PERSONA>_ALL --env prod        # value: legacy

# 2. Re-open legacy API (if needed).
wrangler secret put FLAG_LEGACY_API_GONE --env prod      # value: 0

# 3. Verify legacy E2E green; bump the marker's "Frozen date" field to today and reset the window.
```

## Reviews during the window

- [ ] Day 7 (date: `<date>`) — no rollback required.
- [ ] Day 14 (date: `<date>`) — no rollback required.
- [ ] Day 30 (date: `<date>`) — clear for deletion.

## Why we wait 30 days

Per the migration plan's load-bearing rule #4. The window catches monthly
billing cycles, end-of-month admin reports, and seasonal usage that may
not surface in the first week.

## Next step

After the day-30 review:

- Open the Wave 4B deletion PR per [docs/tickets/wave-4-decommission.md](tickets/wave-4-decommission.md#step-4b--delete-day-30).
- Close `FLAG_LEGACY_HATCH_OPEN` and re-deploy the edge worker.
- Delete this marker after the deletion PR merges.
