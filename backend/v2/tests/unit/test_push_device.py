"""PushDevice invariants (mobile M2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.communications.domain.push_device import (
    MAX_TOKEN_LENGTH,
    InvalidPushDevice,
    PushDevice,
)

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _device(**overrides: Any) -> PushDevice:
    fields: dict[str, Any] = {
        "user_id": "u1",
        "token": "fcm:abc",
        "platform": "ios",
        "app_version": "1.0.0",
        "created_at": NOW,
        "last_seen_at": NOW,
    }
    fields.update(overrides)
    return PushDevice(**fields)


def test_valid_device_builds() -> None:
    assert _device(platform="android", app_version=None).platform == "android"


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": ""},
        {"token": ""},
        {"token": " fcm:abc"},
        {"token": "x" * (MAX_TOKEN_LENGTH + 1)},
        {"platform": "web"},
        {"app_version": "9" * 65},
    ],
)
def test_malformed_device_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(InvalidPushDevice):
        _device(**overrides)
