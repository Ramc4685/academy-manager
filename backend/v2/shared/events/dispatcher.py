"""Event dispatcher with retry, dead-letter, and audit."""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from backend.v2.shared.observability.ops_alerts import capture_exception

from .base import DomainEvent

log = logging.getLogger(__name__)

# Per docs/event-rules.md.
RETRY_DELAYS_SECONDS = [0, 1, 4, 16, 64, 256]
MAX_ATTEMPTS = len(RETRY_DELAYS_SECONDS)

HandlerFn = Callable[[DomainEvent], Awaitable[None]]
HandlerEntry = tuple[str, HandlerFn, type[DomainEvent]]

_REGISTRY: dict[tuple[str, int], list[HandlerEntry]] = {}


def handler(*, event: type[DomainEvent], schema_version: int) -> Callable[[HandlerFn], HandlerFn]:
    """Register an async function as a handler for ``(event.name, schema_version)``.

    Handlers do NOT implement their own idempotency on delivery — the
    dispatcher tracks ``(event_id, handler_name)`` in ``event_handler_runs``.
    """

    def decorator(fn: HandlerFn) -> HandlerFn:
        # We need a stable event name without instantiating; read from the
        # model_fields default of the `name` Literal.
        try:
            name_default = event.model_fields["name"].default  # pydantic v2
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"Event {event!r} must declare a Literal `name`") from exc
        key = (str(name_default), schema_version)
        _REGISTRY.setdefault(key, []).append((f"{fn.__module__}.{fn.__qualname__}", fn, event))
        return fn

    return decorator


class EventDispatcher:
    """Polls the outbox, dispatches events to registered handlers, manages retries.

    Single instance per app process; started by ``main.py`` via ``start()`` and
    stopped on shutdown.
    """

    HANDLER_RUNS = "event_handler_runs"
    DEAD_LETTER = "dead_letter_events"
    AUDIT = "event_audit"

    def __init__(
        self,
        db: AsyncIOMotorDatabase,
        poll_interval_seconds: float = 1.0,
        *,
        worker_id: str | None = None,
        lock_seconds: int = 300,
    ):
        self._db = db
        self._poll_interval = poll_interval_seconds
        self._worker_id = worker_id or f"event-dispatcher:{id(self)}"
        self._lock_seconds = lock_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                for _ in range(50):
                    doc = await self._claim_next_event()
                    if doc is None:
                        break
                    await self._process_event(doc)
            except Exception as exc:  # pragma: no cover - defensive top-level guard
                log.exception("Dispatcher loop iteration failed")
                # Issue #428: without this the loop guard was the end of the
                # line — the dispatcher kept polling and nothing left the box.
                capture_exception(exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass

    async def _claim_next_event(self) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        return await self._db["outbox_events"].find_one_and_update(
            {
                "$or": [
                    {
                        "$and": [
                            {
                                "$or": [
                                    {"status": {"$in": ["pending", "retry"]}},
                                    {"status": {"$exists": False}, "processed": False},
                                ]
                            },
                            {
                                "$or": [
                                    {"next_retry_at": {"$lte": now}},
                                    {"next_retry_at": None},
                                    {"next_retry_at": {"$exists": False}},
                                ]
                            },
                            {
                                "$or": [
                                    {"locked_until": {"$lte": now}},
                                    {"locked_until": None},
                                    {"locked_until": {"$exists": False}},
                                ]
                            },
                        ]
                    },
                    {
                        "$and": [
                            {"status": "processing"},
                            {"locked_until": {"$lte": now}},
                        ]
                    },
                ]
            },
            {
                "$set": {
                    "status": "processing",
                    "locked_until": now + timedelta(seconds=self._lock_seconds),
                    "lock_owner": self._worker_id,
                    "updated_at": now,
                }
            },
            sort=[("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )

    async def _process_event(self, doc: dict[str, Any]) -> None:
        key = (doc["name"], doc["schema_version"])
        handlers = _REGISTRY.get(key)
        if handlers is None:
            # Unknown event or schema version: move to dead-letter and stop trying.
            await self._dead_letter(doc, reason="unregistered_schema_version", error=None)
            await self._mark_event_dead_lettered(doc, error="unregistered_schema_version")
            return

        all_succeeded = True
        for handler_name, fn, event_cls in handlers:
            ok = await self._run_handler_with_retries(doc, handler_name, fn, event_cls)
            all_succeeded = all_succeeded and ok

        if all_succeeded:
            await self._mark_event_processed(doc)

    async def _run_handler_with_retries(
        self,
        doc: dict[str, Any],
        handler_name: str,
        fn: HandlerFn,
        event_cls: type[DomainEvent],
    ) -> bool:
        runs = self._db[self.HANDLER_RUNS]
        prior = await runs.find_one({"event_id": doc["event_id"], "handler_name": handler_name})
        if prior and prior.get("status") == "succeeded":
            await self._audit(doc, handler_name, "skipped_idempotent", latency_ms=0)
            return True

        try:
            event = _reconstruct_event(doc, event_cls)
        except Exception as exc:
            await self._mark_run_failed(doc, handler_name, exc)
            await self._dead_letter(
                doc,
                reason="invalid_event_payload",
                error=str(exc),
                handler_name=handler_name,
            )
            await self._audit(
                doc,
                handler_name,
                "failed",
                latency_ms=0,
                error=str(exc),
            )
            await self._mark_event_dead_lettered(doc, error=str(exc))
            return False

        started_at = datetime.now(UTC)
        try:
            await fn(event)
        except Exception as exc:
            await self._schedule_retry_or_dead_letter(doc, handler_name, exc, started_at)
            return False
        await runs.update_one(
            {"event_id": doc["event_id"], "handler_name": handler_name},
            {
                "$set": {
                    "status": "succeeded",
                    "completed_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
        await self._audit(doc, handler_name, "succeeded", latency_ms=_ms_since(started_at))
        return True

    async def _schedule_retry_or_dead_letter(
        self,
        doc: dict[str, Any],
        handler_name: str,
        exc: Exception,
        started_at: datetime,
    ) -> None:
        attempt_count = int(doc.get("attempt_count") or 0) + 1
        error = str(exc)
        if attempt_count >= MAX_ATTEMPTS:
            await self._mark_run_failed(doc, handler_name, exc)
            await self._dead_letter(
                doc, reason="handler_failed", error=error, handler_name=handler_name
            )
            await self._mark_event_dead_lettered(doc, error=error, attempt_count=attempt_count)
            await self._audit(
                doc,
                handler_name,
                "failed",
                latency_ms=_ms_since(started_at),
                error=error,
            )
            return

        now = datetime.now(UTC)
        delay = RETRY_DELAYS_SECONDS[min(attempt_count, len(RETRY_DELAYS_SECONDS) - 1)]
        await self._db[self.HANDLER_RUNS].update_one(
            {"event_id": doc["event_id"], "handler_name": handler_name},
            {
                "$set": {
                    "status": "retrying",
                    "last_error": error,
                    "attempt_count": attempt_count,
                    "updated_at": now,
                }
            },
            upsert=True,
        )
        await self._db["outbox_events"].update_one(
            _event_update_filter(doc),
            {
                "$set": {
                    "status": "retry",
                    "attempt_count": attempt_count,
                    "next_retry_at": now + timedelta(seconds=delay),
                    "locked_until": None,
                    "lock_owner": None,
                    "last_error": error,
                    "updated_at": now,
                    "processed": False,
                }
            },
        )
        await self._audit(
            doc,
            handler_name,
            "retry_scheduled",
            latency_ms=_ms_since(started_at),
            error=error,
        )

    async def _mark_event_processed(self, doc: dict[str, Any]) -> None:
        now = datetime.now(UTC)
        await self._db["outbox_events"].update_one(
            _event_update_filter(doc),
            {
                "$set": {
                    "processed": True,
                    "processed_at": now,
                    "status": "processed",
                    "locked_until": None,
                    "lock_owner": None,
                    "updated_at": now,
                }
            },
        )

    async def _mark_event_dead_lettered(
        self,
        doc: dict[str, Any],
        *,
        error: str,
        attempt_count: int | None = None,
    ) -> None:
        now = datetime.now(UTC)
        set_fields: dict[str, Any] = {
            "processed": True,
            "processed_at": now,
            "status": "dead_lettered",
            "locked_until": None,
            "lock_owner": None,
            "last_error": error,
            "updated_at": now,
        }
        if attempt_count is not None:
            set_fields["attempt_count"] = attempt_count
        await self._db["outbox_events"].update_one(
            _event_update_filter(doc),
            {"$set": set_fields},
        )

    async def _mark_run_failed(
        self, doc: dict[str, Any], handler_name: str, exc: Exception
    ) -> None:
        await self._db[self.HANDLER_RUNS].update_one(
            {"event_id": doc["event_id"], "handler_name": handler_name},
            {
                "$set": {
                    "status": "failed",
                    "completed_at": datetime.now(UTC),
                    "error": str(exc),
                    "trace": traceback.format_exc(),
                }
            },
            upsert=True,
        )

    async def _dead_letter(
        self,
        doc: dict[str, Any],
        *,
        reason: str,
        error: str | None,
        handler_name: str | None = None,
    ) -> None:
        await self._db[self.DEAD_LETTER].insert_one(
            {
                "event_id": doc["event_id"],
                "event": doc,
                "reason": reason,
                "handler_name": handler_name,
                "error": error,
                "created_at": datetime.now(UTC),
            }
        )

    async def _audit(
        self,
        doc: dict[str, Any],
        handler_name: str,
        outcome: str,
        *,
        latency_ms: int,
        error: str | None = None,
    ) -> None:
        await self._db[self.AUDIT].insert_one(
            {
                "event_id": doc["event_id"],
                "name": doc["name"],
                "schema_version": doc["schema_version"],
                "handler_name": handler_name,
                "outcome": outcome,
                "latency_ms": latency_ms,
                "error": error,
                "academy_id": doc.get("academy_id"),
                "completed_at": datetime.now(UTC),
            }
        )


def _ms_since(start: datetime) -> int:
    return int((datetime.now(UTC) - start).total_seconds() * 1000)


def _event_update_filter(doc: dict[str, Any]) -> dict[str, Any]:
    filter_: dict[str, Any] = {"event_id": doc["event_id"]}
    if doc.get("lock_owner"):
        filter_["lock_owner"] = doc["lock_owner"]
    return filter_


def _reconstruct_event(doc: dict[str, Any], event_cls: type[DomainEvent]) -> DomainEvent:
    payload = doc.get("payload")
    if isinstance(payload, dict) and {
        "name",
        "schema_version",
        "aggregate_id",
        "academy_id",
        "payload",
    }.issubset(payload):
        return event_cls.model_validate(payload)
    return event_cls.model_validate(
        {
            "event_id": doc.get("event_id"),
            "name": doc.get("name"),
            "schema_version": doc.get("schema_version"),
            "aggregate_id": doc.get("aggregate_id"),
            "academy_id": doc.get("academy_id"),
            "occurred_at": doc.get("occurred_at"),
            "payload": payload,
        }
    )
