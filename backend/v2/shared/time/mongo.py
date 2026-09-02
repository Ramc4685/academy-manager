"""Normalize datetimes read back from Mongo."""

from __future__ import annotations

from datetime import UTC, datetime


def ensure_utc(value: datetime) -> datetime:
    """Stamp UTC onto a naive datetime read back from Mongo.

    The Motor client is constructed without ``tz_aware=True``, so stored
    datetimes (which BSON always holds as UTC) come back *naive*. Serialized
    naive, they render as an offset-less ISO string that JS `new Date()` parses
    as browser-LOCAL wall clock — while rows synthesized in Python in the same
    response are aware and serialize with a trailing ``Z``. Two shapes in one
    array mean opposite things to the client, so normalize on read.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
