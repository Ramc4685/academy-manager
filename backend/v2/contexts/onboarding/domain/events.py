"""Onboarding domain events."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from backend.v2.shared.events.base import DomainEvent


class ApplicationStartedPayload(BaseModel):
    model_config = {"frozen": True}
    application_id: str
    parent_user_id: str


class ApplicationStarted(DomainEvent):
    name: Literal["Onboarding.ApplicationStarted"] = "Onboarding.ApplicationStarted"
    schema_version: Literal[1] = 1
    payload: ApplicationStartedPayload


class ApplicationApprovedPayload(BaseModel):
    model_config = {"frozen": True}
    application_id: str
    parent_user_id: str
    session_id: str
    payment_id: str


class ApplicationApproved(DomainEvent):
    name: Literal["Onboarding.ApplicationApproved"] = "Onboarding.ApplicationApproved"
    schema_version: Literal[1] = 1
    payload: ApplicationApprovedPayload
