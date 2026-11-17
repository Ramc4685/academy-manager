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
from backend.v2.contexts.identity.domain.models import (
    AcademyMembership,
    MagicLinkRecord,
    User,
)

ACADEMY = "acad-1"


class _FakeRepo:
    def __init__(self) -> None:
        self.by_hash: dict[str, MagicLinkRecord] = {}

    async def insert(self, record: MagicLinkRecord) -> None:
        self.by_hash[record.token_hash] = record

    async def get_by_hash(self, token_hash: str) -> MagicLinkRecord | None:
        return self.by_hash.get(token_hash)

    async def revoke_unused_for_user(self, *, user_id: str, academy_id: str) -> None:
        self.by_hash = {
            h: r
            for h, r in self.by_hash.items()
            if not (r.user_id == user_id and r.academy_id == academy_id and r.used_at is None)
        }

    async def mark_used(self, token_hash: str, *, used_at: datetime) -> bool:
        record = self.by_hash.get(token_hash)
        if record is None or record.used_at is not None:
            return False
        self.by_hash[token_hash] = record.model_copy(update={"used_at": used_at})
        return True


class _FakeTokens:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    async def create_custom_token(self, uid: str) -> str:
        self.calls.append(uid)
        if self.fail:
            raise RuntimeError("firebase admin unavailable")
        return f"custom-{uid}"


class _FakeUsers:
    """The roster id on the link maps to a users row with its own Firebase uid."""

    def __init__(self, users: dict[str, User] | None = None) -> None:
        self.users = (
            users
            if users is not None
            else {
                "parent-1": User(
                    user_id="parent-1",
                    firebase_uid="fb-parent-1",
                    email="p@example.com",
                    display_name="P",
                )
            }
        )

    async def get_by_id(self, user_id: str) -> User | None:
        return self.users.get(user_id)


class _FakeMemberships:
    """Keyed by (academy_id, user_id); defaults to parent-1 as an active parent."""

    def __init__(self, rows: dict[tuple[str, str], AcademyMembership] | None = None) -> None:
        self.rows = (
            rows
            if rows is not None
            else {(ACADEMY, "parent-1"): _membership(ACADEMY, "parent-1", ("parent",))}
        )

    async def get_for_user_in_academy(
        self, *, user_id: str, academy_id: str, aliases: object = None
    ) -> AcademyMembership | None:
        return self.rows.get((academy_id, user_id))


def _membership(
    academy_id: str, user_id: str, roles: tuple[str, ...], status: str = "active"
) -> AcademyMembership:
    return AcademyMembership(
        membership_id=f"m-{academy_id}-{user_id}",
        academy_id=academy_id,
        user_id=user_id,
        roles=roles,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
    )


def _consume(
    repo: _FakeRepo,
    tokens: _FakeTokens,
    users: _FakeUsers | None = None,
    memberships: _FakeMemberships | None = None,
):
    return ConsumeMagicLink(
        links=repo,
        tokens=tokens,
        users=users or _FakeUsers(),
        memberships=memberships or _FakeMemberships(),
    )


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

    result = await _consume(repo, tokens).execute(raw, academy_id=ACADEMY)

    assert result.custom_token == "custom-fb-parent-1"
    assert result.next_path == "/parent/payments"
    assert tokens.calls == ["fb-parent-1"]
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
    consume = _consume(repo, tokens)

    await consume.execute(raw, academy_id=ACADEMY)

    with pytest.raises(MagicLinkInvalid):
        await consume.execute(raw, academy_id=ACADEMY)
    # The Firebase custom token was minted exactly once — the replay never
    # reached the token port.
    assert tokens.calls == ["fb-parent-1"]


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
        await _consume(repo, tokens).execute(raw, academy_id=ACADEMY)
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
        await _consume(repo, tokens).execute(raw, academy_id="acad-2")
    assert tokens.calls == []
    # A rejected cross-tenant attempt must NOT burn the token.
    assert repo.by_hash[_hash_token(raw)].used_at is None


@pytest.mark.asyncio
async def test_consume_rejects_unknown_token() -> None:
    repo = _FakeRepo()
    tokens = _FakeTokens()

    with pytest.raises(MagicLinkInvalid):
        await _consume(repo, tokens).execute("nope", academy_id=ACADEMY)


# ---------------------------------------------------------------------------
# L4 regressions: real Firebase uid, retryable on Firebase failure, one live link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_mints_for_the_users_firebase_uid_not_the_roster_id() -> None:
    repo = _FakeRepo()
    tokens = _FakeTokens()
    raw = _seed(repo, user_id="roster-7")
    users = _FakeUsers(
        {
            "roster-7": User(
                user_id="roster-7",
                firebase_uid="fb-real",
                email="p@example.com",
                display_name="P",
            )
        }
    )

    memberships = _FakeMemberships(
        {(ACADEMY, "roster-7"): _membership(ACADEMY, "roster-7", ("parent",))}
    )

    result = await _consume(repo, tokens, users, memberships).execute(raw, academy_id=ACADEMY)

    assert tokens.calls == ["fb-real"]
    assert result.custom_token == "custom-fb-real"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "users",
    [
        {},
        {"parent-1": User(user_id="parent-1", email="p@example.com", display_name="P")},
        {
            "parent-1": User(
                user_id="parent-1",
                firebase_uid="fb-1",
                email="p@example.com",
                display_name="P",
                global_status="disabled",
            )
        },
    ],
    ids=["no-users-row", "no-firebase-account", "disabled"],
)
async def test_consume_refuses_without_a_usable_login_and_keeps_the_link(users) -> None:
    repo = _FakeRepo()
    tokens = _FakeTokens()
    raw = _seed(repo)

    with pytest.raises(MagicLinkInvalid):
        await _consume(repo, tokens, _FakeUsers(users)).execute(raw, academy_id=ACADEMY)
    assert tokens.calls == []
    assert repo.by_hash[_hash_token(raw)].used_at is None


@pytest.mark.asyncio
async def test_a_firebase_failure_does_not_burn_the_link() -> None:
    repo = _FakeRepo()
    raw = _seed(repo)

    with pytest.raises(RuntimeError):
        await _consume(repo, _FakeTokens(fail=True)).execute(raw, academy_id=ACADEMY)
    assert repo.by_hash[_hash_token(raw)].used_at is None

    result = await _consume(repo, _FakeTokens()).execute(raw, academy_id=ACADEMY)
    assert result.custom_token == "custom-fb-parent-1"


@pytest.mark.asyncio
async def test_issuing_a_new_link_revokes_the_parents_older_unused_links() -> None:
    repo = _FakeRepo()
    old = _seed(repo, token="old-token")
    other_parent = _seed(repo, token="other", user_id="parent-2", magic_link_id="ml-2")

    new = await IssueMagicLink(repo).execute(
        user_id="parent-1", academy_id=ACADEMY, next_path="/parent/dashboard"
    )

    assert _hash_token(old) not in repo.by_hash
    assert _hash_token(other_parent) in repo.by_hash
    assert _hash_token(new) in repo.by_hash


# ---------------------------------------------------------------------------
# Parent-membership gate: only an active parent of the token's academy redeems
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    [
        pytest.param(
            {(ACADEMY, "parent-1"): _membership(ACADEMY, "parent-1", ("coach", "admin"))},
            id="staff-only",
        ),
        pytest.param(
            {("acad-other", "parent-1"): _membership("acad-other", "parent-1", ("parent",))},
            id="parent-in-wrong-academy",
        ),
        pytest.param(
            {(ACADEMY, "parent-1"): _membership(ACADEMY, "parent-1", ("parent",), "removed")},
            id="inactive-membership",
        ),
        pytest.param({}, id="no-membership"),
    ],
)
async def test_consume_rejects_a_user_without_an_active_parent_membership(
    rows: dict[tuple[str, str], AcademyMembership],
) -> None:
    repo = _FakeRepo()
    tokens = _FakeTokens()
    raw = _seed(repo)

    with pytest.raises(MagicLinkInvalid):
        await _consume(repo, tokens, memberships=_FakeMemberships(rows)).execute(
            raw, academy_id=ACADEMY
        )
    assert tokens.calls == []
    assert repo.by_hash[_hash_token(raw)].used_at is None


@pytest.mark.asyncio
async def test_consume_accepts_an_active_parent_who_is_also_staff() -> None:
    repo = _FakeRepo()
    tokens = _FakeTokens()
    raw = _seed(repo)
    rows = {(ACADEMY, "parent-1"): _membership(ACADEMY, "parent-1", ("coach", "parent"))}

    result = await _consume(repo, tokens, memberships=_FakeMemberships(rows)).execute(
        raw, academy_id=ACADEMY
    )

    assert result.custom_token == "custom-fb-parent-1"
    assert repo.by_hash[_hash_token(raw)].used_at is not None
