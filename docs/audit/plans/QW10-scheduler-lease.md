# QW10 — Lease-lock scheduler jobs
Status: DONE
Size: S · Depends on: none · Tracker: ../TRACKER.md

## Problem
APScheduler jobs rely on `max_instances=1`, which is per-process only. On >1 Fly machine every job runs on every machine — duplicate dunning retries, duplicate digests, duplicate webhook-event processing. `main.py` even carries a comment deferring "cross-machine exclusivity" to leader election; a Mongo lease is the cheap fix.

## Current behavior (verified)
- `backend/v2/main.py:457-521` registers 6 jobs, all `max_instances=1`: `process_scheduled_resume_actions` (cron 02:00), `expire_makeup_requests` (02:30), `process_stripe_webhook_events` (60s), `reconcile_stripe_payment_intents` (10m), `process_dunning_retries` (60m), `send_coach_daily_digests` (hourly). Bodies are local closures, e.g. `_process_scheduled_resumes` at :262-283 (per-academy `tenant_scope` loop).
- The claim pattern already exists in `backend/v2/shared/events/dispatcher.py:104-149`: `find_one_and_update` setting `status/locked_until/lock_owner` atomically — copy the shape, not the code.

## Implementation steps
1. New module `backend/v2/shared/scheduling/lease.py` (new `scheduling/` package beside `events/` — dispatcher is outbox-specific, leases are not):
   ```python
   @asynccontextmanager
   async def job_lease(db, name: str, ttl: timedelta, worker_id: str): ...
   ```
   Acquire: `find_one_and_update` on `scheduler_leases` upserting `{_id: name}` where `locked_until` is missing/`<= now`, setting `locked_until = now + ttl`, `lock_owner`. Yields `True` if acquired, `False` if another machine holds it. Release: on clean exit set `locked_until` to now (early release); on exception let TTL expire.
2. In `main.py`, wrap each job body:
   `async with job_lease(db, "process_dunning_retries", ttl=..., worker_id=os.environ.get("FLY_MACHINE_ID", uuid)) as ok: if not ok: return`.
   Wrap all 6 jobs. TTL per job ≈ 2× expected runtime, min 5 minutes (interval jobs must have TTL < interval only via early release, so early-release on success matters for the 60s webhook job — or give it TTL 55s).
3. Create a TTL-free unique index implicitly via `_id`; no migration needed (upsert creates the collection).
4. Keep `max_instances=1` (still guards in-process overlap).

## Verification
- Unit test `backend/v2/tests/shared/test_job_lease.py` against the same Mongo test harness the dispatcher tests use: (a) two concurrent acquires of one name → exactly one wins; (b) expired `locked_until` is reclaimable; (c) clean exit releases early; (d) exception leaves the lease to expire.
- One integration-style test: call a wrapped job twice concurrently, assert the body ran once (counter fake).
- Full backend suite green; boot the app locally and confirm jobs still fire (log lines like `scheduled_resume_actions_processed`).

## Risks / rollback
- A crash mid-job blocks re-run until TTL expiry — acceptable for these cadences; keep TTLs modest. Clock skew between machines can shorten/lengthen leases slightly — TTL margins cover it. Rollback: remove the `job_lease` wrapper lines (bodies unchanged).

## PR checklist
- [ ] Release note if backend/ or frontend/ changed (per AGENTS.md)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
