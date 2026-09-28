"""The academy's default phone calling code (row 11).

Derived at read time from ``academies.country`` (the #990 field). Absent, blank
or US -> ``"1"``, which is exactly what every WhatsApp link and CRM duplicate
fold used before, so BLNO (no ``country`` stored) is unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.shared.comms.phone_country import (
    DEFAULT_CALLING_CODE,
    academy_calling_code_lookup,
    calling_code_for_country,
)


@pytest.mark.parametrize("country", [None, "", "  ", "US", "us", " Us ", "CA"])
def test_north_american_or_unset_country_is_plus_one(country: str | None) -> None:
    assert calling_code_for_country(country) == "1"
    assert DEFAULT_CALLING_CODE == "1"


def test_unmapped_country_falls_back_to_the_default() -> None:
    # Only US academies exist (Stripe Connect refuses others, #990), so an
    # unknown code keeps today's behaviour rather than guessing.
    assert calling_code_for_country("ZZ") == "1"


class _Academies:
    def __init__(self, docs: list[dict[str, Any]], *, fail: bool = False) -> None:
        self._docs = docs
        self._fail = fail
        self.queries: list[dict[str, Any]] = []

    async def find_one(self, query: dict[str, Any], projection: Any = None) -> Any:
        self.queries.append(query)
        if self._fail:
            raise RuntimeError("mongo down")
        return next((d for d in self._docs if d["academy_id"] == query["academy_id"]), None)


class _Db:
    def __init__(self, academies: _Academies) -> None:
        self._academies = academies

    def __getitem__(self, name: str) -> _Academies:
        assert name == "academies"
        return self._academies


async def test_lookup_reads_only_the_asked_academy() -> None:
    academies = _Academies(
        [
            {"academy_id": "blno"},
            {"academy_id": "acad_blno_badminton", "country": "US"},
            {"academy_id": "other", "country": "CA"},
        ]
    )
    lookup = academy_calling_code_lookup(_Db(academies))
    assert await lookup("blno") == "1"
    assert await lookup("acad_blno_badminton") == "1"
    assert await lookup("missing") == "1"
    assert [q["academy_id"] for q in academies.queries] == [
        "blno",
        "acad_blno_badminton",
        "missing",
    ]


async def test_lookup_failure_degrades_to_the_default() -> None:
    lookup = academy_calling_code_lookup(_Db(_Academies([], fail=True)))
    assert await lookup("blno") == "1"
