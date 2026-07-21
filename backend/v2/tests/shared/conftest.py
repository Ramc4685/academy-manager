"""Fixtures for shared-primitive tests.

Mirrors ``backend/v2/tests/contract/conftest.py``: an in-process
``mongomock-motor`` database, the same harness the dispatcher tests use.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio


@pytest_asyncio.fixture
async def db() -> AsyncIterator[object]:
    try:
        from mongomock_motor import AsyncMongoMockClient  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        import pytest

        pytest.skip("mongomock-motor not installed")
    client = AsyncMongoMockClient()
    yield client["test_db"]
