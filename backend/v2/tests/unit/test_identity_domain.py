"""Pure domain tests for Identity."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.v2.contexts.identity.domain.models import User


def _user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "user_id": "u1",
        "email": "coach@example.com",
        "display_name": "Coach Carter",
        "roles": ("coach",),
        "is_active": True,
        "academy_id": "test-academy",
    }
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


def test_user_is_frozen() -> None:
    user = _user()
    with pytest.raises(ValidationError):
        user.roles = ("admin",)  # type: ignore[misc]


def test_has_role() -> None:
    user = _user(roles=("coach", "admin"))
    assert user.has_role("coach")
    assert user.has_role("admin")
    assert not user.has_role("parent")


def test_email_validation() -> None:
    with pytest.raises(ValidationError):
        _user(email="not-an-email")
