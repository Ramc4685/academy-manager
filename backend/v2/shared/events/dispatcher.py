"""Event dispatcher with retry, dead-letter, and audit."""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from motor.motor_asyncio import AsyncIOMotorDatabase

from .base import DomainEvent

log = logging.getLogger(__name__)

# Per docs/event-rules.md.
RETRY_DELAYS_SECONDS = [0, 1, 4, 16, 64, 256]
MAX_ATTEMPTS = len(RETRY_DELAYS_SECONDS)

HandlerFn = Callable[[DomainEvent], Awaitable[None]]

_REGISTRY: dict[tuple[str, int], list[tuple[str, HandlerFn]]] = {}


def handler(
    *, event: type[DomainEvent], schema_version: int
) -> Callable[[HandlerFn], HandlerFn]:
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
        _REGISTRY.setdefault(key, []).append((f"{fn.__module__}.{fn.__qualname__}", fn))
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

    def __init__(self, db: AsyncIOMotorDatabase, poll_interval_seconds: float = 1.0):
        self._db = db
        self._poll_interval = poll_interval_seconds
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
        outbox_collection = self._db["outbox_events"]
        while not self._stop.is_set():
            try:
                cursor = (
                    outbox_collection.find({"processed": False})
                    .sort([("created_at", 1)])
                    .limit(50)
                )
                async for doc in cursor:
                    await self._process_event(doc)
            except Exception:  # pragma: no cover - defensive top-level guard
                log.exception("Dispatcher loop iteration failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass

    async def _process_event(self, doc: dict[str, Any]) -> None:
        key = (doc["name"], doc["schema_version"])
        handlers = _REGISTRY.get(key)
        if handlers is None:
            # Unknown event or schema version: move to dead-letter and stop trying.
            await self._dead_letter(doc, reason="unregistered_schema_version", error=None)
            await self._db["outbox_events"].update_one(
                {"event_id": doc["event_id"]},
                {"$set": {"processed": True, "processed_at": datetime.now(timezone.utc)}},
            )
            return

        all_succeeded = True
        for handler_name, fn in handlers:
            ok = await self._run_handler_with_retries(doc, handler_name, fn)
            all_succeeded = all_succeeded and ok

        if all_succeeded:
            await self._db["outbox_events"].update_one(
                {"event_id": doc["event_id"]},
                {"$set": {"processed": True, "processed_at": datetime.now(timezone.utc)}},
            )

    async def _run_handler_with_retries(
        self, doc: dict[str, Any], handler_name: str, fn: HandlerFn
    ) -> bool:
        runs = self._db[self.HANDLER_RUNS]
        prior = await runs.find_one(
            {"event_id": doc["event_id"], "handler_name": handler_name}
        )
        if prior and prior.get("status") == "succeeded":
            await self._audit(doc, handler_name, "skipped_idempotent", latency_ms=0)
            return True

        # Reconstruct the event for the handler.
        event = DomainEvent.model_construct(**doc["payload"])

        for attempt in range(MAX_ATTEMPTS):
            delay = RETRY_DELAYS_SECONDS[attempt]
            if delay > 0:
                await asyncio.sleep(delay)
            started_at = datetime.now(timezone.utc)
            try:
                await fn(event)
            except Exception as exc:
                if attempt + 1 == MAX_ATTEMPTS:
                    await self._mark_run_failed(doc, handler_name, exc)
                    await self._dead_letter(doc, reason="handler_failed", error=str(exc), handler_name=handler_name)
                    await self._audit(
                        doc,
                        handler_name,
                        "failed",
                        latency_ms=_ms_since(started_at),
                        error=str(exc),
                    )
                    return False
                continue
            await runs.update_one(
                {"event_id": doc["event_id"], "handler_name": handler_name},
                {
                    "$set": {
                        "status": "succeeded",
                        "completed_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
            await self._audit(
                doc, handler_name, "succeeded", latency_ms=_ms_since(started_at)
            )
            return True
        return False

    async def _mark_run_failed(
        self, doc: dict[str, Any], handler_name: str, exc: Exception
    ) -> None:
        await self._db[self.HANDLER_RUNS].update_one(
            {"event_id": doc["event_id"], "handler_name": handler_name},
            {
                "$set": {
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc),
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
                "created_at": datetime.now(timezone.utc),
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
                "completed_at": datetime.now(timezone.utc),
            }
        )


def _ms_since(start: datetime) -> int:
    return int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
