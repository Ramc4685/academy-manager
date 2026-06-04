from __future__ import annotations

import pytest

from backend.v2.main import _scheduler_academy_ids


class _FakeAcademyRepo:
    def __init__(self, docs: list[dict[str, object]]) -> None:
        self._ids = [str(doc.get("academy_id") or "") for doc in docs]

    async def list_ids(self) -> list[str]:
        return self._ids


@pytest.mark.asyncio
async def test_scheduler_academy_ids_are_unique_and_include_default() -> None:
    academies = _FakeAcademyRepo(
        [
            {"academy_id": "academy-a"},
            {"academy_id": "academy-b"},
            {"academy_id": "academy-a"},
            {"academy_id": ""},
        ]
    )

    assert await _scheduler_academy_ids(academies, "default-academy") == [
        "academy-a",
        "academy-b",
        "default-academy",
    ]
