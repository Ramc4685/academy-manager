# Pause Resume Autopay Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build fixed-date and indefinite pause requests that coordinate roster pause/resume with Stripe autopay, using a durable daily scheduled resume worker.

**Architecture:** Enrollment remains the source of truth for roster state. Pause approval orchestrates existing enrollment pause behavior, pauses Stripe collection, and creates a durable scheduled action only for fixed-date pauses. A daily worker attempts due resumes; Stripe resumes only after roster resume succeeds.

**Tech Stack:** FastAPI, Pydantic v2, MongoDB/Motor, existing v2 DDD contexts, Stripe gateway anti-corruption layer, Next.js 15 frontend, React Query.

---

## Preconditions

- Work on a clean feature branch from `main` or reconcile the current dirty branch first.
- Read the approved spec: `docs/superpowers/specs/2026-06-03-pause-resume-autopay-design.md`.
- Follow `AGENTS.md`: update the active test ledger with `scripts/dev/test_result.py`.

## Task 1: Start Test Ledger

**Files:**
- Modify: `docs/test-results/active/<generated-ledger>.md`

**Step 1: Create ledger**

Run:

```bash
scripts/dev/test_result.py start "pause resume autopay" --problem "Verify fixed/indefinite pause requests, scheduled resume actions, roster capacity blocking, and Stripe pause/resume coordination"
```

Expected: a new active ledger path is printed.

**Step 2: Log implementation start**

Run:

```bash
scripts/dev/test_result.py log pause-resume-autopay --agent main --status working --message "Starting TDD implementation for pause resume autopay workflow"
```

Expected: ledger updated.
## Task 2: Add Scheduled Action Domain Model and Migration

**Files:**
- Create: `backend/v2/contexts/enrollment/application/use_cases/scheduled_actions.py`
- Create: `backend/v2/contexts/enrollment/infrastructure/mongo_scheduled_action_repo.py`
- Create: `backend/v2/migrations/0113_scheduled_enrollment_actions.py`
- Test: `backend/v2/tests/application/test_scheduled_enrollment_actions.py`

**Step 1: Write failing model/repo tests**

Create tests for:

- fixed `resume_from_pause` action can be created.
- duplicate `(academy_id, pause_request_id, action_type)` is idempotent.
- due query returns only `status="pending"` and `run_at <= now`.
- status transitions to `succeeded`, `blocked_capacity`, and `failed`.

Example shape:

```python
async def test_due_actions_return_only_pending_due_rows():
    now = datetime(2026, 6, 3, 7, 0, tzinfo=UTC)
    repo = FakeScheduledActionRepository()
    await repo.add(ScheduledEnrollmentAction(..., run_at=now, status="pending"))
    await repo.add(ScheduledEnrollmentAction(..., run_at=now + timedelta(days=1), status="pending"))
    due = await repo.list_due(now=now, limit=50)
    assert [row.action_id for row in due] == ["due-action"]
```

**Step 2: Run tests to verify failure**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/application/test_scheduled_enrollment_actions.py -q
```

Expected: FAIL because model/repo/use case do not exist.

**Step 3: Implement model and port**

In `scheduled_actions.py`, add:

```python
ScheduledActionStatus = Literal["pending", "succeeded", "blocked_capacity", "failed", "cancelled"]
ScheduledActionType = Literal["resume_from_pause"]

class ScheduledEnrollmentAction(BaseModel):
    model_config = {"frozen": True}
    action_id: str
    academy_id: str
    action_type: ScheduledActionType
    enrollment_id: str
    pause_request_id: str
    run_at: datetime
    status: ScheduledActionStatus = "pending"
    attempt_count: int = 0
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
```

Add `ScheduledEnrollmentActionRepository` protocol with `add`, `list_due`, `mark_succeeded`, `mark_blocked_capacity`, `mark_failed`.

**Step 4: Implement Mongo repo**

Use tenant-scoped repository conventions from `mongo_pause_request_repo.py`. Query due actions with:

```python
{"academy_id": current_academy_id(), "status": "pending", "run_at": {"$lte": now}}
```

**Step 5: Add migration**

In `0113_scheduled_enrollment_actions.py`:

```python
version = "0113"

async def up(db):
    collection = db["scheduled_enrollment_actions"]
    await collection.create_index(
        [("academy_id", 1), ("status", 1), ("run_at", 1)],
        name="due_scheduled_enrollment_actions",
    )
    await collection.create_index(
        [("academy_id", 1), ("pause_request_id", 1), ("action_type", 1)],
        unique=True,
        name="unique_pause_action",
    )
```

**Step 6: Run tests**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/application/test_scheduled_enrollment_actions.py -q
```

Expected: PASS.

## Task 3: Add Stripe Pause and Resume Gateway Methods

**Files:**
- Modify: `backend/v2/contexts/billing/application/ports.py`
- Modify: `backend/v2/contexts/billing/infrastructure/stripe_gateway.py`
- Modify: `backend/v2/contexts/billing/infrastructure/fake_stripe_gateway.py`
- Test: `backend/v2/tests/unit/test_stripe_gateway.py`

**Step 1: Write failing tests**

Add fake-gateway tests for:

- `pause_subscription_collection(stripe_subscription_id, behavior="void")` records the call.
- `resume_subscription_collection(stripe_subscription_id)` records the call.

If real Stripe unit tests already exist, add mocked tests that assert:

```python
stripe.Subscription.modify("sub_123", pause_collection={"behavior": "void"})
stripe.Subscription.modify("sub_123", pause_collection="")
```

**Step 2: Run tests to verify failure**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/unit/test_stripe_gateway.py -q
```

Expected: FAIL because methods are missing.

**Step 3: Extend `StripeGateway` protocol**

Add:

```python
async def pause_subscription_collection(
    self,
    stripe_subscription_id: str,
    *,
    behavior: Literal["void", "keep_as_draft", "mark_uncollectible"] = "void",
) -> None: ...

async def resume_subscription_collection(self, stripe_subscription_id: str) -> None: ...
```

**Step 4: Implement real gateway**

In `RealStripeGateway`:

```python
async def pause_subscription_collection(...):
    await asyncio.to_thread(
        lambda: self._stripe.Subscription.modify(
            stripe_subscription_id,
            pause_collection={"behavior": behavior},
        )
    )

async def resume_subscription_collection(...):
    await asyncio.to_thread(
        lambda: self._stripe.Subscription.modify(
            stripe_subscription_id,
            pause_collection="",
        )
    )
```

**Step 5: Implement fake gateway**

Add `paused_subscriptions` and `resumed_subscriptions` call lists.

**Step 6: Run tests**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/unit/test_stripe_gateway.py -q
```

Expected: PASS.

## Task 4: Extend Pause Request Contract

**Files:**
- Modify: `backend/v2/contexts/enrollment/application/use_cases/pause_requests.py`
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_pause_request_repo.py`
- Modify: `backend/v2/interfaces/parent/views.py`
- Modify: `backend/v2/interfaces/admin/views.py`
- Test: `backend/v2/tests/application/test_pause_requests.py`

**Step 1: Write failing tests**

Cover:

- `pause_kind="fixed"` requires `resume_on`.
- `pause_kind="indefinite"` rejects or ignores `resume_on`.
- existing period-only payload is no longer the preferred contract.
- repo round-trips `pause_kind` and `resume_on`.

**Step 2: Run tests**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/application/test_pause_requests.py -q
```

Expected: FAIL.

**Step 3: Update models**

Add:

```python
PauseKind = Literal["fixed", "indefinite"]

class PauseRequest(BaseModel):
    pause_kind: PauseKind = "fixed"
    resume_on: date | None = None
```

Add a Pydantic validator:

```python
if self.pause_kind == "fixed" and self.resume_on is None:
    raise ValueError("resume_on is required for fixed pauses")
if self.pause_kind == "indefinite" and self.resume_on is not None:
    raise ValueError("resume_on is only allowed for fixed pauses")
```

Keep `period` only if existing code still needs compatibility. Prefer deriving `period` from `resume_on` or deprecating it in the UI.

**Step 4: Update DTOs**

Add `pause_kind` and `resume_on` to `CreatePauseRequest`, `PauseRequestView`, and `AdminPauseRequestView`.

**Step 5: Update Mongo mapper**

Read missing legacy docs as:

```python
pause_kind = doc.get("pause_kind") or "fixed"
resume_on = doc.get("resume_on")
```

**Step 6: Run tests**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/application/test_pause_requests.py -q
```

Expected: PASS.

## Task 5: Orchestrate Pause Approval

**Files:**
- Modify: `backend/v2/contexts/enrollment/application/use_cases/pause_requests.py`
- Modify: `backend/v2/composition/admin.py`
- Test: `backend/v2/tests/application/test_pause_request_approval_workflow.py`

**Step 1: Write failing tests**

Cover:

- approving fixed pause calls roster pause, pauses Stripe, and creates scheduled action.
- approving indefinite pause calls roster pause and pauses Stripe but creates no scheduled action.
- approval is idempotent if request already approved.
- missing subscription should still pause roster and return meaningful billing metadata/error state, not crash the roster workflow.

**Step 2: Run tests**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/application/test_pause_request_approval_workflow.py -q
```

Expected: FAIL.

**Step 3: Inject dependencies into `ApprovePauseRequest`**

Add optional constructor dependencies:

- `pause_enrollment: PauseEnrollment`
- `scheduled_actions: ScheduledEnrollmentActionRepository`
- `subscriptions: SubscriptionRepository`
- `stripe: StripeGateway`
- `clock`

**Step 4: Implement approval orchestration**

Workflow:

```python
request = await pause_requests.approve(...)
await pause_enrollment.execute(PauseEnrollmentCommand(...))
subscription = await subscriptions.latest_for_enrollment(request.enrollment_id)
if subscription and subscription.stripe_subscription_id:
    await stripe.pause_subscription_collection(subscription.stripe_subscription_id, behavior="void")
if request.pause_kind == "fixed":
    await scheduled_actions.add(...)
return request
```

Do not set Stripe `resumes_at` for seat-releasing pauses.

**Step 5: Wire admin composition**

In `compose_admin`, instantiate `MongoScheduledEnrollmentActionRepository` and pass dependencies to `ApprovePauseRequest`.

**Step 6: Run tests**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/application/test_pause_request_approval_workflow.py -q
```

Expected: PASS.

## Task 6: Add Daily Resume Worker Use Case

**Files:**
- Create: `backend/v2/contexts/enrollment/application/use_cases/process_scheduled_resume_actions.py`
- Modify: `backend/v2/composition/admin.py`
- Modify: `backend/v2/main.py`
- Test: `backend/v2/tests/application/test_process_scheduled_resume_actions.py`

**Step 1: Write failing tests**

Cover:

- due action with available capacity resumes enrollment, removes waitlist, resumes Stripe, marks action `succeeded`.
- due action with full capacity leaves enrollment paused/waitlisted, does not resume Stripe, marks `blocked_capacity`.
- unexpected Stripe failure marks action `failed` and captures `last_error`.

**Step 2: Run tests**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/application/test_process_scheduled_resume_actions.py -q
```

Expected: FAIL.

**Step 3: Implement use case**

Create:

```python
class ProcessScheduledResumeActions:
    async def execute(self, *, now: datetime | None = None, limit: int = 50) -> ProcessResult:
        actions = await scheduled_actions.list_due(now=now or self._clock(), limit=limit)
        ...
```

For each action:

1. call `ResumeEnrollment.execute(action.enrollment_id, actor_id="system", reason="scheduled resume")`
2. if `CapacityExceeded`, mark `blocked_capacity`
3. on success, lookup subscription and call `stripe.resume_subscription_collection`
4. mark `succeeded`

**Step 4: Wire a daily lightweight app task**

Use APScheduler already present in `backend/requirements.txt`, or a minimal `asyncio` loop if the project already prefers that. Preferred shape in `main.py` lifespan:

```python
scheduler = AsyncIOScheduler(timezone="UTC")
scheduler.add_job(
    app.state.admin.process_scheduled_resume_actions.execute,
    "cron",
    hour=7,
    minute=0,
    kwargs={"limit": 100},
)
scheduler.start()
app.state.scheduler = scheduler
```

Shutdown scheduler in lifespan cleanup.

**Step 5: Run tests**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/application/test_process_scheduled_resume_actions.py -q
```

Expected: PASS.

## Task 7: Add API and Admin Visibility

**Files:**
- Modify: `backend/v2/interfaces/admin/deps.py`
- Modify: `backend/v2/interfaces/admin/dashboard_routes.py`
- Modify: `backend/v2/interfaces/admin/pause_routes.py`
- Modify: `backend/v2/interfaces/admin/views.py`
- Test: `backend/v2/tests/interface/test_admin_pause_requests.py`

**Step 1: Write failing interface tests**

Cover:

- admin pause list returns `pause_kind` and `resume_on`.
- approval response includes the new fields.
- dashboard attention includes blocked scheduled resume actions.

**Step 2: Run tests**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/interface/test_admin_pause_requests.py -q
```

Expected: FAIL.

**Step 3: Update admin views/routes**

Expose the fields and add a blocked-capacity attention item such as:

```text
Scheduled resume blocked
1 enrollment could not resume because the class is full.
```

**Step 4: Run tests**

Run:

```bash
cd backend && source .venv/bin/activate && pytest v2/tests/interface/test_admin_pause_requests.py -q
```

Expected: PASS.

## Task 8: Update Parent and Admin UI

**Files:**
- Modify: `frontend/lib/api/parent.ts`
- Modify: `frontend/lib/api/admin.ts`
- Modify: `frontend/app/(parent)/parent/payments/page.tsx`
- Modify: `frontend/app/(admin)/admin/pause-requests/page.tsx`
- Test: existing frontend typecheck; add node tests only if local API helpers already have coverage.

**Step 1: Update TypeScript types**

Add:

```ts
type PauseKind = "fixed" | "indefinite";
resume_on?: string | null;
pause_kind: PauseKind;
```

**Step 2: Update parent form**

Replace month-only field with:

- segmented/radio control for fixed-date vs indefinite
- date input for fixed-date
- reason textarea
- helper text: `We will attempt to resume this enrollment on the requested date if a seat is available.`

**Step 3: Update admin queue**

Display:

- requested resume date or `Indefinite`
- approval consequence text: `Releases seat, moves student to waitlist, pauses billing.`

**Step 4: Run typecheck**

Run:

```bash
cd frontend && pnpm typecheck
```

Expected: PASS.

## Task 9: Full Focused Verification

**Files:**
- Modify: active test ledger.

**Step 1: Backend focused tests**

Run:

```bash
cd backend && source .venv/bin/activate && pytest \
  v2/tests/application/test_scheduled_enrollment_actions.py \
  v2/tests/application/test_pause_requests.py \
  v2/tests/application/test_pause_request_approval_workflow.py \
  v2/tests/application/test_process_scheduled_resume_actions.py \
  v2/tests/interface/test_admin_pause_requests.py \
  -q
```

Expected: PASS.

**Step 2: Backend lint**

Run:

```bash
cd backend && source .venv/bin/activate && ruff format --check v2 && ruff check v2
```

Expected: PASS.

**Step 3: Frontend verification**

Run:

```bash
cd frontend && pnpm typecheck && pnpm lint
```

Expected: PASS.

**Step 4: Log verification**

Run:

```bash
scripts/dev/test_result.py verify pause-resume-autopay --message "Focused backend tests, ruff, frontend typecheck/lint passed"
```

Expected: ledger updated.

**Step 5: Final status check**

Run:

```bash
git status --short --branch
git diff --stat
```

Expected: only related pause/resume/autopay files changed, plus ledger updates.

## Task 10: Manual Local Smoke

**Files:**
- No code changes expected.

**Step 1: Start stack**

Run:

```bash
scripts/local_test_stack.sh all
```

Expected: backend `http://127.0.0.1:8001`, frontend `http://localhost:3001`.

**Step 2: Parent flow**

Use `http://blno.localhost:3001/parent/payments`:

1. submit fixed-date pause request.
2. confirm request appears with resume date.
3. submit indefinite pause request if there is another enrollment.

**Step 3: Admin flow**

Use admin pause requests page:

1. approve fixed-date pause.
2. verify enrollment leaves roster and appears/retains waitlist status.
3. verify Stripe fake/local test call records pause collection.

**Step 4: Worker smoke**

Trigger the process use case through a temporary script or test-only route only if one already exists. Prefer backend application test over adding a production manual endpoint.

**Step 5: Log smoke**

Run:

```bash
scripts/dev/test_result.py verify pause-resume-autopay --message "Manual local smoke completed for parent pause request and admin approval"
```

Expected: ledger updated.
