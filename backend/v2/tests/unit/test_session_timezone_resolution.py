"""One fallback ladder for a session's wall clock (hardcoded-values row 7).

Session zone -> academy zone -> the legacy single-tenant guess. The legacy
rung is BLNO's zone, so BLNO (``America/Chicago`` on its academy record) reads
exactly the same zone it always has; any other tenant now reads its own.
"""

from __future__ import annotations

import logging

import pytest

from backend.v2.shared.time import LEGACY_FALLBACK_TIMEZONE, resolve_session_timezone

_LOGGER = "backend.v2.shared.time.academy_timezone"


def test_legacy_fallback_is_blno_zone() -> None:
    # Pins today's behaviour: the historical hardcoded fallback.
    assert LEGACY_FALLBACK_TIMEZONE == "America/Chicago"


def test_session_zone_wins() -> None:
    assert resolve_session_timezone("America/New_York", "America/Chicago") == "America/New_York"


def test_session_zone_is_kept_verbatim_so_callers_still_validate() -> None:
    # Money and write paths build their own ZoneInfo and fail on a bad name
    # exactly as before; the resolver must not silently swap it.
    assert resolve_session_timezone("Not/AZone", "America/Chicago") == "Not/AZone"


def test_blno_session_without_zone_reads_academy_chicago() -> None:
    assert resolve_session_timezone(None, "America/Chicago") == "America/Chicago"
    assert resolve_session_timezone("", "America/Chicago") == "America/Chicago"
    assert resolve_session_timezone("  ", "America/Chicago") == "America/Chicago"


def test_other_tenant_session_without_zone_reads_its_academy_zone() -> None:
    assert resolve_session_timezone(None, "America/Los_Angeles") == "America/Los_Angeles"


def test_both_missing_uses_legacy_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert resolve_session_timezone(None, None) == "America/Chicago"
    assert any("America/Chicago" in rec.getMessage() for rec in caplog.records)


def test_invalid_academy_zone_falls_through_to_legacy(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert resolve_session_timezone(None, "Mars/Olympus") == "America/Chicago"
    assert caplog.records


def test_empty_academy_zone_uses_legacy() -> None:
    assert resolve_session_timezone(None, "") == "America/Chicago"
