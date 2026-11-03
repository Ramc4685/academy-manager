"""Push sender construction (mobile M3): the one place the FCM adapter is built.

Off by default. Until the owner sets ``PUSH_DELIVERY_ENABLED=true`` every push
goes to the in-memory stub, so nothing reaches a phone.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.communications.application.ports import PushSendPort
from backend.v2.contexts.communications.infrastructure.fcm_push_send_port import FcmPushSendPort
from backend.v2.contexts.communications.infrastructure.stub_push_send_port import (
    StubPushSendPort,
)
from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import firebase_app


def _build_push_sender(settings: Any) -> PushSendPort:
    if getattr(settings, "push_delivery_enabled", False):
        return FcmPushSendPort(app_provider=firebase_app)
    return StubPushSendPort()
