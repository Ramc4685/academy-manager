"""Push sender construction (mobile M3): the one place the FCM adapter is built.

Off by default. Until the owner sets ``PUSH_DELIVERY_ENABLED=true`` every push
goes to the in-memory stub, so nothing reaches a phone.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.communications.application.ports import PushSendPort
from backend.v2.contexts.communications.application.use_cases.notify_message_by_push import (
    NotifyMessageByPush,
)
from backend.v2.contexts.communications.application.use_cases.send_push_to_user import (
    SendPushToUser,
)
from backend.v2.contexts.communications.domain.push_events import enabled_push_events
from backend.v2.contexts.communications.infrastructure.fcm_push_send_port import FcmPushSendPort
from backend.v2.contexts.communications.infrastructure.mongo_push_device_repo import (
    MongoPushDeviceRepository,
)
from backend.v2.contexts.communications.infrastructure.stub_push_send_port import (
    StubPushSendPort,
)
from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import firebase_app


def _build_push_sender(settings: Any) -> PushSendPort:
    if getattr(settings, "push_delivery_enabled", False):
        return FcmPushSendPort(app_provider=firebase_app)
    return StubPushSendPort()


def compose_send_push_to_user(db: Any, settings: Any) -> SendPushToUser:
    """The push the parent notifiers send after their email (class cancelled,
    waitlist offer, urgent announcement, dues reminders)."""
    return SendPushToUser(
        devices=MongoPushDeviceRepository(db),
        sender=_build_push_sender(settings),
        enabled_events=enabled_push_events(getattr(settings, "push_extra_events", "")),
    )


def compose_message_push(db: Any, settings: Any) -> NotifyMessageByPush:
    """Push for DMs, academy broadcasts and routine class announcements (L11)."""
    from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
        MongoAudienceResolver,
    )
    from backend.v2.contexts.communications.infrastructure.mongo_email_preference_repo import (
        MongoEmailPreferenceRepository,
    )

    return NotifyMessageByPush(
        push=compose_send_push_to_user(db, settings),
        audiences=MongoAudienceResolver(db=db),
        preferences=MongoEmailPreferenceRepository(db),
    )
