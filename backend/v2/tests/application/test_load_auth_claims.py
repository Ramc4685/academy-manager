"""Use-case tests for LoadAuthClaims with port fakes."""

from __future__ import annotations

import pytest

from backend.v2.contexts.identity.application.use_cases.load_auth_claims import LoadAuthClaims
from backend.v2.contexts.identity.domain.errors import InvalidToken, UserInactive, UserNotFound
from backend.v2.contexts.identity.domain.models import User


class FakeVerifier:
    def __init__(self, claims: dict[str, object] | None = None, raise_with: Exception | None = None) -> None:
        self._claims = claims
        self._raise = raise_with

    async def verify(self, id_token: str) -> dict[str, object]:
        if self._raise:
            raise self._raise
        return dict(self._claims or {})


class FakeUserRepo:
    def __init__(self, users: list[User]) -> None:
        self._by_email = {u.email: u for u in users}

    async def get_by_email(self, email: str) -> User | None:
        return self._by_email.get(email)  # type: ignore[arg-type]

    async def get_by_id(self, user_id: str) -> User | None:
        for u in self._by_email.values():
            if u.user_id == user_id:
                return u
        return None


def _coach() -> User:
    return User(
        user_id="u-coach",
        email="coach@example.com",
        display_name="Coach Carter",
        roles=("coach",),
        is_active=True,
        academy_id="test-academy",
    )


@pytest.mark.asyncio
async def test_happy_path_returns_claims() -> None:
    uc = LoadAuthClaims(
        verifier=FakeVerifier(claims={"email": "coach@example.com"}),
        users=FakeUserRepo([_coach()]),
    )
    claims = await uc.execute("fake-token")
    assert claims.user_id == "u-coach"
    assert claims.email == "coach@example.com"
    assert claims.academy_id == "test-academy"
    assert claims.roles == ("coach",)


@pytest.mark.asyncio
async def test_invalid_token_raised() -> None:
    uc = LoadAuthClaims(
        verifier=FakeVerifier(raise_with=ValueError("bad sig")),
        users=FakeUserRepo([]),
    )
    with pytest.raises(InvalidToken):
        await uc.execute("bad")


@pytest.mark.asyncio
async def test_missing_email_raises() -> None:
    uc = LoadAuthClaims(
        verifier=FakeVerifier(claims={}),
        users=FakeUserRepo([_coach()]),
    )
    with pytest.raises(InvalidToken):
        await uc.execute("ok")


@pytest.mark.asyncio
async def test_unknown_user_raises_not_found() -> None:
    uc = LoadAuthClaims(
        verifier=FakeVerifier(claims={"email": "ghost@example.com"}),
        users=FakeUserRepo([_coach()]),
    )
    with pytest.raises(UserNotFound):
        await uc.execute("ok")


@pytest.mark.asyncio
async def test_inactive_user_raises() -> None:
    inactive = _coach().model_copy(update={"is_active": False})
    uc = LoadAuthClaims(
        verifier=FakeVerifier(claims={"email": inactive.email}),
        users=FakeUserRepo([inactive]),
    )
    with pytest.raises(UserInactive):
        await uc.execute("ok")
