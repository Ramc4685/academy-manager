"""Unit tests for the parent magic-link use cases.

Covers the security-critical behaviours with in-memory fakes: only the token
hash is stored, redemption is single-use / race-safe, expiry and tenant
mismatch are rejected with the right error, and ``next_path`` is open-redirect
safe.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from backend.v2.contexts.identity.application.use_cases.magic_link import (
    ConsumeMagicLink,
    IssueMagicLink,
    _hash_token,
    _safe_next,
)
from backend.v2.contexts.identity.domain.errors import (
    MagicLinkExpired,
    MagicLinkInvalid,
)
from backend.v2.contexts.identity.domain.models import MagicLinkRecord

ACADEMY = "acad-1"


class _FakeRepo:
    def __init__(self) -> None:
        self.by_hash: dict[str, MagicLinkRecord] = {}

    async def insert(self, record: MagicLinkRecord) -> None:
        self.by_hash[record.token_hash] = record

    async def get_by_hash(self, token_hash: str) -> MagicLinkRecord | None:
        return self.by_hash.get(token_hash)

    async def mark_used(self, token_hash: str, *, used_at: datetime) -> bool:
        record = self.by_hash.get(token_hash)
        if record is None or record.used_at is not None:
            return False
        self.by_hash[token_hash] = record.model_copy(update={"used_at": used_at})
        return True


class _FakeTokens:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_custom_token(self, uid: str) -> str:
        self.calls.append(uid)
        return f"custom-{uid}"


def _seed(repo: _FakeRepo, **overrides: object) -> str:
    """Insert a record directly and return the raw token it hashes from."""
    token = str(overrides.pop("token", "raw-token"))
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "magic_link_id": "ml-1",
        "token_hash": _hash_token(token),
        "user_id": "parent-1",
        "academy_id": ACADEMY,
        "next_path": "/parent/payments",
        "created_at": now,
        "expires_at": now + timedelta(hours=72),
        "purge_at": now + timedelta(hours=72) + timedelta(days=7),
        "used_at": None,
    }
    defaults.update(overrides)
    repo.by_hash[str(defaults["token_hash"])] = MagicLinkRecord(**defaults)  # type: ignore[arg-type]
    return token


# ---------------------------------------------------------------------------
# _safe_next
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/parent/payments", "/parent/payments"),
        ("/parent/dashboard", "/parent/dashboard"),
        ("//evil.example.com", "/parent/dashboard"),  # protocol-relative
        ("https://evil.example.com", "/parent/dashboard"),  # absolute URL
        ("parent/payments", "/parent/dashboard"),  # missing leading slash
        ("", "/parent/dashboard"),
        (None, "/parent/dashboard"),
    ],
)
def test_safe_next_only_allows_same_site_paths(value: str | None, expected: str) -> None:
    assert _safe_next(value) == expected


# ---------------------------------------------------------------------------
# IssueMagicLink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_stores_only_the_hash_and_returns_raw_token() -> None:
    repo = _FakeRepo()
    issue = IssueMagicLink(repo)

    token = await issue.execute(
        user_id="parent-1", academy_id=ACADEMY, next_path="/parent/payments"
    )

    assert token  # a non-empty raw token is returned to the caller
    assert token not in repo.by_hash  # the raw token itself is never stored
    stored = repo.by_hash[_hash_token(token)]
    assert stored.token_hash == _hash_token(token)
    assert stored.user_id == "parent-1"
    assert stored.academy_id == ACADEMY
    assert stored.next_path == "/parent/payments"
    assert stored.used_at is None
    # TTL + purge grace: expires ~72h out, purge ~7d after that.
    assert timedelta(hours=71) < (stored.expires_at - stored.created_at) < timedelta(hours=73)
    assert timedelta(days=6) < (stored.purge_at - stored.expires_at) < timedelta(days=8)


@pytest.mark.asyncio
async def test_issue_sanitizes_unsafe_next_path() -> None:
    repo = _FakeRepo()
    issue = IssueMagicLink(repo)

    token = await issue.execute(
        user_id="parent-1", academy_id=ACADEMY, next_path="https://evil.example.com"
    )

    assert repo.by_hash[_hash_token(token)].next_path == "/parent/dashboard"


# ---------------------------------------------------------------------------
# ConsumeMagicLink — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_happy_path_returns_custom_token_and_next_path() -> None:
    repo = _FakeRepo()
    tokens = _FakeTokens()
    raw = _seed(repo, next_path="/parent/payments")

    result = await ConsumeMagicLink(links=repo, tokens=tokens).execute(raw, academy_id=ACADEMY)

    assert result.custom_token == "custom-parent-1"
    assert result.next_path == "/parent/payments"
    assert tokens.calls == ["parent-1"]
    # The token is now marked used.
    assert repo.by_hash[_hash_token(raw)].used_at is not None


# ---------------------------------------------------------------------------
# ConsumeMagicLink — single use / race
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_is_single_use() -> None:
    repo = _FakeRepo()
    tokens = _FakeTokens()
    raw = _seed(repo)
    consume = ConsumeMagicLink(links=repo, tokens=tokens)

    await consume.execute(raw, academy_id=ACADEMY)

    with pytest.raises(MagicLinkInvalid):
        await consume.execute(raw, academy_id=ACADEMY)
    # The Firebase custom token was minted exactly once — the replay never
    # reached the token port.
    assert tokens.calls == ["parent-1"]


# ---------------------------------------------------------------------------
# ConsumeMagicLink — expiry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_rejects_expired_token() -> None:
    repo = _FakeRepo()
    tokens = _FakeTokens()
    past = datetime.now(UTC) - timedelta(hours=1)
    raw = _seed(repo, expires_at=past)

    with pytest.raises(MagicLinkExpired):
        await ConsumeMagicLink(links=repo, tokens=tokens).execute(raw, academy_id=ACADEMY)
    assert tokens.calls == []  # never signed anyone in


# ---------------------------------------------------------------------------
# ConsumeMagicLink — tenant binding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_rejects_token_from_another_tenant() -> None:
    repo = _FakeRepo()
    tokens = _FakeTokens()
    raw = _seed(repo, academy_id="acad-1")

    with pytest.raises(MagicLinkInvalid):
        await ConsumeMagicLink(links=repo, tokens=tokens).execute(raw, academy_id="acad-2")
    assert tokens.calls == []
    # A rejected cross-tenant attempt must NOT burn the token.
    assert repo.by_hash[_hash_token(raw)].used_at is None


@pytest.mark.asyncio
async def test_consume_rejects_unknown_token() -> None:
    repo = _FakeRepo()
    tokens = _FakeTokens()

    with pytest.raises(MagicLinkInvalid):
        await ConsumeMagicLink(links=repo, tokens=tokens).execute("nope", academy_id=ACADEMY)
