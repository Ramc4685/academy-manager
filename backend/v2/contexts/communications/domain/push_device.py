"""Push-notification device registrations (mobile apps, slice M2).

One row per FCM registration token. A token identifies one app install on one
phone, so it belongs to exactly one user at a time: when a second user signs in
on a shared family phone, the token moves to them and the first user stops
receiving pushes there. Nothing is sent yet; the push channel (M3) reads these
rows the way email reads addresses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, get_args

from backend.v2.contexts.communications.domain.errors import CommunicationsError

PushPlatform = Literal["ios", "android"]
PUSH_PLATFORMS: frozenset[str] = frozenset(get_args(PushPlatform))

#: FCM tokens are ~160-200 chars today; the cap only stops abuse of the store.
MAX_TOKEN_LENGTH = 4096
MAX_APP_VERSION_LENGTH = 64


class InvalidPushDevice(CommunicationsError, ValueError):
    """Raised when a device registration is malformed."""


@dataclass(frozen=True, slots=True)
class PushDevice:
    user_id: str
    token: str
    platform: PushPlatform
    app_version: str | None
    #: When this token was first registered (it survives a move to another user).
    created_at: datetime
    last_seen_at: datetime

    def __post_init__(self) -> None:
        if not self.user_id:
            raise InvalidPushDevice("user_id is required")
        if not self.token or self.token != self.token.strip():
            raise InvalidPushDevice("token must be non-empty with no surrounding whitespace")
        if len(self.token) > MAX_TOKEN_LENGTH:
            raise InvalidPushDevice("token is too long")
        if self.platform not in PUSH_PLATFORMS:
            raise InvalidPushDevice(f"unsupported platform: {self.platform!r}")
        if self.app_version is not None and len(self.app_version) > MAX_APP_VERSION_LENGTH:
            raise InvalidPushDevice("app_version is too long")
