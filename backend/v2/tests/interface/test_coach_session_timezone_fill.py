"""Coach views fill a zoneless session's ``timezone`` from the academy (row 19).

The coach UI renders every time in ``session.timezone`` and only falls back
to UTC when it is null, so a legacy session with no zone showed a 6pm Chicago
class as 11pm. The BFF now fills ``s.timezone or <academy zone>``; a session's
own zone always passes through untouched. BLNO (academy America/Chicago) is
pinned: its seeded sessions already carry Chicago, and a zoneless one now
reads Chicago too.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.v2.interfaces.coach.deps import CoachUseCases, academy_zone_for_sessions
from backend.v2.tests.interface.conftest import _build_use_cases, _coach_claims, _make_app


def _client(seed, *, academy_zone: str | None, zoneless: set[str]) -> TestClient:
    seed = {
        **seed,
        "sessions": [
            s.model_copy(update={"timezone": None}) if s.session_id in zoneless else s
            for s in seed["sessions"]
        ],
    }
    use_cases = _build_use_cases(seed)
    calls: list[str] = []

    async def lookup(academy_id: str) -> str | None:
        calls.append(academy_id)
        return academy_zone

    use_cases.get_academy_timezone = lookup
    client = TestClient(_make_app(_coach_claims(), use_cases))
    client.lookup_calls = calls  # type: ignore[attr-defined]
    return client


@pytest.fixture()
def blno_zoneless_client(seed) -> Iterator[TestClient]:
    with _client(seed, academy_zone="America/Chicago", zoneless={"s-today-1"}) as client:
        yield client


def _zones(body: dict) -> dict[str, str | None]:
    return {s["session_id"]: s["timezone"] for s in body["sessions"]}


def test_today_fills_zoneless_session_with_blno_academy_zone(blno_zoneless_client) -> None:
    r = blno_zoneless_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    assert _zones(r.json()) == {"s-today-1": "America/Chicago", "s-today-2": "America/Chicago"}


def test_sessions_fills_zoneless_session_with_blno_academy_zone(blno_zoneless_client) -> None:
    r = blno_zoneless_client.get("/api/v2/coach/sessions")
    assert r.status_code == 200, r.text
    assert _zones(r.json()) == {"s-today-1": "America/Chicago", "s-today-2": "America/Chicago"}


def test_session_zone_passes_through_and_academy_fills_only_the_gap(seed) -> None:
    with _client(seed, academy_zone="America/Denver", zoneless={"s-today-2"}) as client:
        r = client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    assert _zones(r.json()) == {"s-today-1": "America/Chicago", "s-today-2": "America/Denver"}


def test_all_zoned_sessions_skip_the_academy_lookup(seed) -> None:
    with _client(seed, academy_zone="America/Denver", zoneless=set()) as client:
        r = client.get("/api/v2/coach/sessions")
        assert r.status_code == 200, r.text
        assert client.lookup_calls == []  # type: ignore[attr-defined]
    assert set(_zones(r.json()).values()) == {"America/Chicago"}


def test_no_academy_zone_leaves_null_for_the_client_last_resort(seed) -> None:
    with _client(seed, academy_zone=None, zoneless={"s-today-1"}) as client:
        r = client.get("/api/v2/coach/today?date=2026-05-16")
    assert _zones(r.json())["s-today-1"] is None


@pytest.mark.asyncio
async def test_invalid_or_failing_academy_zone_is_ignored() -> None:
    class _Session:
        timezone = None

    async def bad(_academy_id: str) -> str | None:
        return "Mars/Olympus"

    async def broken(_academy_id: str) -> str | None:
        raise RuntimeError("down")

    uc = CoachUseCases.__new__(CoachUseCases)
    uc.get_academy_timezone = bad
    assert await academy_zone_for_sessions([_Session()], use_cases=uc, academy_id="a") is None
    uc.get_academy_timezone = broken
    assert await academy_zone_for_sessions([_Session()], use_cases=uc, academy_id="a") is None
