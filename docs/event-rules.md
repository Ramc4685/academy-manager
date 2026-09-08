# Domain Event Rules

**Status:** Authoritative. Implemented in `backend/v2/shared/events/`.
**Ticket:** P0-09
**Last reviewed:** 2026-05-16

Domain events are the only cross-context state mutation channel ([data-ownership.md](data-ownership.md)). They are first-class citizens: named, versioned, durable, retried, audited.

## Naming

Format: `<Context>.<Aggregate><PastTenseVerb>`.

Examples:

- `Identity.UserInvited`
- `Enrollment.SessionCreated`
- `Enrollment.WaitlistPromoted`
- `Coaching.AttendanceMarked`
- `Billing.PaymentSucceeded`
- `Billing.PaymentRefunded`

Rules:

- **Past tense.** Events are facts about things that have happened. `UserInvites` is wrong; `UserInvited` is right.
- **Aggregate before verb.** `PaymentSucceeded`, not `SuccessfulPayment`.
- **Context prefix is the producing context**, not the topic.
- **No commands as events.** `MarkAttendance` is a command. `AttendanceMarked` is the event that results.

## Event Schema

Every event is a Pydantic v2 model in `backend/v2/contexts/<context>/domain/events.py`, extending a base:

```python
class DomainEvent(BaseModel):
    event_id: ULID            # unique per event
    name: str                 # "Billing.PaymentSucceeded"
    schema_version: int       # starts at 1
    aggregate_id: str         # ID of the producing aggregate
    academy_id: str           # tenant
    occurred_at: datetime     # producer's UTC timestamp
    payload: dict             # context-specific
```

Each concrete event subclasses with a typed `payload`:

```python
class PaymentSucceeded(DomainEvent):
    name: Literal["Billing.PaymentSucceeded"] = "Billing.PaymentSucceeded"
    schema_version: Literal[1] = 1
    payload: PaymentSucceededPayload
```

## Schema Versioning

- `schema_version` starts at 1 and increments on every breaking payload change.
- Handlers register for `(name, schema_version)` tuples. Unknown versions go to `dead_letter_events` with reason `unregistered_schema_version` — never silently dropped.
- A new version may run alongside the old until handlers migrate; both are valid until the old one is explicitly retired in an ADR.

## Outbox Pattern

Events are written to the `outbox_events` collection in the **same Mongo transaction** as the aggregate change.

```python
async with mongo_transaction() as session:
    await attendance_repo.save(attendance, session=session)
    await outbox.append(AttendanceMarked(...), session=session)
```

A background poller (asyncio task in `shared/events/dispatcher.py`):

1. Selects unprocessed events ordered by `created_at`.
2. Dispatches each to registered handlers in-process.
3. Marks the event row processed.
4. Logs to `event_audit`.

This guarantees **at-least-once delivery** across the Stripe webhook boundary. Handlers must be idempotent.

## Idempotent Handlers

Every handler is keyed by `(event_id, handler_name)`. Before running, the dispatcher checks `event_handler_runs`:

- If a row exists with `status=succeeded`, skip.
- If `status=running` and stale (> 5 minutes), allow re-entry (assume previous instance crashed).
- Otherwise, mark `running`, execute, mark `succeeded` or `failed`.

Handler code does **not** implement its own idempotency on event delivery — the framework does. Handlers focus on the business logic.

## Retry Policy

Failed handlers retry with exponential backoff:

| Attempt | Delay |
|---|---|
| 1 | immediate (initial dispatch) |
| 2 | 1s |
| 3 | 4s |
| 4 | 16s |
| 5 | 64s |
| 6 | 256s |

After **5 retries (6 total attempts)**, the event moves to `dead_letter_events` and pages oncall (`severity=high`).

## Dead Letter & Replay

`dead_letter_events` stores:

- The full event document.
- The handler name(s) that failed.
- The last error and stack trace.
- A `created_at` for retention.

Operators replay via `backend/v2/scripts/replay_event.py <event_id>`:

```bash
python -m backend.v2.scripts.replay_event 01HXYZ...
```

The CLI:

1. Reads the dead-letter event.
2. Re-enqueues it to `outbox_events` with a new `event_id` and a `replayed_from` reference.
3. Marks the dead-letter row as `replayed`.

Manual replays show up in `event_audit` with reason `manual_replay`.

## Audit Trail

Every dispatch attempt writes to `event_audit`:

```python
{
    "event_id": ...,
    "name": ...,
    "schema_version": ...,
    "handler_name": ...,
    "started_at": ...,
    "completed_at": ...,
    "outcome": "succeeded" | "failed" | "skipped_idempotent",
    "error": ...,  # if failed
    "latency_ms": ...,
    "academy_id": ...,
}
```

Retention: 400 days via Mongo TTL on `completed_at` (migration 0166 extended it from the original 90 days: this collection is the financial audit trail once Sentry's 30-day logs are gone).

## Handler Registration

```python
from shared.events import handler
from contexts.billing.domain.events import PaymentSucceeded

@handler(event=PaymentSucceeded, schema_version=1)
async def confirm_enrollment_on_payment(event: PaymentSucceeded) -> None:
    ...
```

- Registration is module-level. The composition root imports handler modules to register them.
- A handler may register for multiple events.
- A handler may **not** call into another context's repository directly. It must call an application use case.

## Indexes

Per [plan §0.7](../../../../.claude/plans/write-a-detailed-plan-curried-trinket.md):

| Collection | Index | Purpose |
|---|---|---|
| `outbox_events` | `(processed, created_at)` | Dispatcher polling |
| `event_handler_runs` | `(event_id, handler_name)` unique | Idempotency lookup |
| `dead_letter_events` | `(created_at)` | Operator review by time |
| `event_audit` | `(completed_at)` TTL 400d | Retention (was 90d until migration 0166) |
| `event_audit` | `(academy_id, name, completed_at)` | Per-tenant per-event timeline |

## Anti-Patterns

- ❌ Emitting an event from a route or use case **without** writing to the outbox inside the same transaction. This loses events on crash.
- ❌ A handler that mutates its own context's aggregate directly. If `Billing.PaymentSucceeded` triggers a billing-side mutation, the original use case should have done it. Events are for **other contexts** to react.
- ❌ Catching handler exceptions inside the handler. Let them propagate — the dispatcher's retry policy handles failure.
- ❌ Using events as a substitute for return values. If you need a synchronous result, call a use case.
- ❌ Emitting a "command" event (`PleaseConfirmEnrollment`). Events describe what happened; commands tell something to happen. They are different things.

## Wave 1A Scope

Wave 1A produces exactly one event: `Coaching.AttendanceMarked`. It has no consumers yet (audit only). Wave 1B is the first slice that wires a producer-consumer pair (offline-attendance sync triggering downstream actions).

## Anti-Pattern Detection (CI)

A custom pytest check (`backend/v2/tests/structural/test_event_rules.py`) verifies:

- Every event class extends `DomainEvent`.
- Every event has a `Literal` `name` and `schema_version`.
- Every place that calls `outbox.append` is inside a `mongo_transaction` context.
- No handler imports `contexts.<other>.infrastructure` or `contexts.<other>.domain`.
