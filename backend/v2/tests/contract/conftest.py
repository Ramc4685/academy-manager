"""Contract-test fixtures.

Uses ``mongomock-motor`` (already pinned in requirements.txt) to give us an
in-process async Mongo. Faster than testcontainers, sufficient for repo
tests that exercise filters, indexes intentionally not asserted here —
those are covered by the migration smoke test.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest_asyncio

from backend.v2.shared.tenancy.context import tenant_scope


@pytest_asyncio.fixture
async def db() -> AsyncIterator[object]:
    try:
        from mongomock_motor import AsyncMongoMockClient  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        import pytest

        pytest.skip("mongomock-motor not installed")
    client = AsyncMongoMockClient()
    yield client["test_db"]


@pytest_asyncio.fixture
async def acad():
    with tenant_scope("test-academy"):
        yield "test-academy"


@pytest_asyncio.fixture
async def other_acad():
    """Used to assert tenant isolation."""
    with tenant_scope("other-academy"):
        yield "other-academy"
