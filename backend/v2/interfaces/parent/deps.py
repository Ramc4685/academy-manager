"""Parent BFF dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.application.use_cases.start_checkout import StartCheckout
from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    GetApplicationStatus,
    PatchApplication,
    StartApplication,
    TransitionApplication,
)


@dataclass
class ParentUseCases:
    start_application: StartApplication
    patch_application: PatchApplication
    get_application_status: GetApplicationStatus
    transition_application: TransitionApplication
    start_checkout: StartCheckout
    handle_webhook_event: HandleWebhookEvent
    list_payments_for_parent: object  # bound to a callable in composition; opaque to routes


def get_parent_use_cases(request: Request) -> ParentUseCases:
    return request.app.state.parent  # type: ignore[no-any-return]
