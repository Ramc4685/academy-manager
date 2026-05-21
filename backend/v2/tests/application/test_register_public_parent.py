from __future__ import annotations

import pytest

from backend.v2.contexts.identity.application.use_cases.register_public_parent import (
    RegisterPublicParent,
)
from backend.v2.contexts.identity.domain.errors import InvalidToken, UserInactive
from backend.v2.contexts.identity.domain.models import User


class FakeVerifier:
    def __init__(self, claims: dict[str, object]) -> None:
        self.claims = claims

    async def verify(self, id_token: str) -> dict[str, object]:
        assert id_token == "firebase-token"
        return self.claims


class FakeUsers:
    def __init__(self, existing: User | None = None) -> None:
        self.existing = existing
        self.ensure_calls: list[dict[str, str]] = []

    async def get_by_email(self, email: str) -> User | None:
        return (
            self.existing
            if self.existing and self.existing.email.lower() == email.lower()
            else None
        )

    async def get_by_id(self, user_id: str) -> User | None:
        return None

    async def ensure_parent_user(self, *, email: str, display_name: str, firebase_uid: str) -> User:
        self.ensure_calls.append(
            {
                "email": email,
                "display_name": display_name,
                "firebase_uid": firebase_uid,
            }
        )
        return User(
            user_id=firebase_uid,
            email=email,
            display_name=display_name,
            roles=("parent",),
            is_active=True,
            academy_id="academy-a",
        )


@pytest.mark.asyncio
async def test_register_public_parent_bootstraps_parent_role() -> None:
    users = FakeUsers()
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {
                "email": "new.parent@example.com",
                "uid": "firebase-parent-1",
                "name": "New Parent",
            }
        ),
        users=users,
    )

    user = await use_case.execute("firebase-token")

    assert user.roles == ("parent",)
    assert user.user_id == "firebase-parent-1"
    assert users.ensure_calls == [
        {
            "email": "new.parent@example.com",
            "display_name": "New Parent",
            "firebase_uid": "firebase-parent-1",
        }
    ]


@pytest.mark.asyncio
async def test_register_public_parent_requires_email_and_uid() -> None:
    use_case = RegisterPublicParent(
        verifier=FakeVerifier({"email": "parent@example.com"}),
        users=FakeUsers(),
    )

    with pytest.raises(InvalidToken):
        await use_case.execute("firebase-token")


@pytest.mark.asyncio
async def test_register_public_parent_does_not_reactivate_disabled_user() -> None:
    existing = User(
        user_id="u-disabled",
        email="parent@example.com",
        display_name="Disabled Parent",
        roles=("parent",),
        is_active=False,
        academy_id="academy-a",
    )
    use_case = RegisterPublicParent(
        verifier=FakeVerifier({"email": "parent@example.com", "uid": "firebase-parent-1"}),
        users=FakeUsers(existing),
    )

    with pytest.raises(UserInactive):
        await use_case.execute("firebase-token")
