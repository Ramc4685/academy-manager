"""@idempotent decorator.

Wraps an async use case so duplicate calls with the same key return the cached
result without re-executing. Keys are stored in the `idempotency_keys`
collection with TTL 7d (migration P0-16).

Usage:

    @idempotent(key_from=lambda cmd: f"mark_attendance:{cmd.mutation_id}")
    async def mark_attendance(self, cmd: MarkAttendanceCommand) -> AttendanceResult:
        ...
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

_T = TypeVar("_T")


class IdempotencyStore(Protocol):
    """Persistence interface for idempotency results.

    Implemented by `MongoIdempotencyStore` in production. Replaceable with an
    in-memory fake in tests.
    """

    async def get(self, key: str) -> dict[str, Any] | None: ...
    async def put(self, key: str, value: dict[str, Any]) -> None: ...


def _serialize(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return {"_type": "pydantic", "data": value.model_dump(mode="json")}
    if value is None:
        return {"_type": "none"}
    # Best-effort JSON roundtrip for simple types.
    return {"_type": "raw", "data": json.loads(json.dumps(value, default=str))}


def _deserialize(stored: dict[str, Any], expected_type: type | None = None) -> Any:
    if stored["_type"] == "none":
        return None
    if stored["_type"] == "pydantic" and expected_type is not None:
        assert issubclass(expected_type, BaseModel)
        return expected_type.model_validate(stored["data"])
    return stored.get("data")


def idempotent(
    *,
    key_from: Callable[..., str],
    store_attr: str = "_idempotency_store",
    result_type: type | None = None,
) -> Callable[[Callable[..., Awaitable[_T]]], Callable[..., Awaitable[_T]]]:
    """Mark an async use-case method idempotent.

    Args:
        key_from: Callable that derives the idempotency key from the same
            (self, ...) args the wrapped function receives.
        store_attr: Attribute name on ``self`` holding the IdempotencyStore.
            Allows use cases to inject the store via __init__.
        result_type: Optional Pydantic model type for typed rehydration of
            cached results. Without it, dicts/lists/strings rehydrate as-is.
    """

    def decorator(fn: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
        @wraps(fn)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> _T:
            store: IdempotencyStore | None = getattr(self, store_attr, None)
            if store is None:
                raise RuntimeError(
                    f"@idempotent requires `self.{store_attr}` to be an IdempotencyStore"
                )
            key = key_from(self, *args, **kwargs)
            existing = await store.get(key)
            if existing is not None:
                return _deserialize(existing["value"], result_type)
            result = await fn(self, *args, **kwargs)
            await store.put(
                key,
                {
                    "value": _serialize(result),
                    "stored_at": datetime.now(UTC).isoformat(),
                },
            )
            return result

        return wrapper

    return decorator
