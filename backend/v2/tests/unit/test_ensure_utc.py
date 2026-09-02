"""`ensure_utc` normalizes the two datetime shapes one API array can carry.

The Motor client is built without ``tz_aware=True``, so datetimes read back
from Mongo are naive while rows synthesized in Python are aware. Serialized
side by side, an offset-less string and a `...Z` string mean opposite things to
JS `new Date()`. Normalizing on read is the backend half of that fix.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from backend.v2.shared.time import ensure_utc


def test_naive_mongo_datetime_is_stamped_utc() -> None:
    assert ensure_utc(datetime(2026, 9, 3, 23, 0)) == datetime(2026, 9, 3, 23, 0, tzinfo=UTC)


def test_aware_non_utc_datetime_is_converted_not_relabelled() -> None:
    chicago = datetime(2026, 9, 3, 18, 0, tzinfo=ZoneInfo("America/Chicago"))

    converted = ensure_utc(chicago)

    # 18:00 CDT is 23:00Z — the instant is preserved, the wall clock is not.
    assert converted == datetime(2026, 9, 3, 23, 0, tzinfo=UTC)
    assert converted.hour == 23


def test_already_utc_datetime_is_unchanged() -> None:
    value = datetime(2026, 9, 3, 23, 0, tzinfo=UTC)

    assert ensure_utc(value) == value
