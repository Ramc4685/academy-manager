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
    """Activate tenant ContextVar for the test. Sync set/reset works fine
    inside the async test body; pytest-asyncio's teardown across event
    loops trips up the context-manager form."""
    from backend.v2.shared.tenancy.context import _current as _tv

    token = _tv.set("test-academy")
    try:
        yield "test-academy"
    finally:
        try:
            _tv.reset(token)
        except (ValueError, LookupError):
            # The reset can fail if pytest-asyncio finalises us from a
            # different Context; that's harmless — the next test sets its
            # own value.
            pass


@pytest_asyncio.fixture
async def other_acad():
    """Used to assert tenant isolation."""
    from backend.v2.shared.tenancy.context import _current as _tv

    token = _tv.set("other-academy")
    try:
        yield "other-academy"
    finally:
        try:
            _tv.reset(token)
        except (ValueError, LookupError):
            pass
