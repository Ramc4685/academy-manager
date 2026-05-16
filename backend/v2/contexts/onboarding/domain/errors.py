"""Onboarding domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class ApplicationNotFound(DomainError):
    code = "Onboarding.ApplicationNotFound"
    status_code = 404


class ApplicationNotEditable(DomainError):
    code = "Onboarding.ApplicationNotEditable"
    status_code = 409


class WaiverNotAccepted(DomainError):
    code = "Onboarding.WaiverNotAccepted"
    status_code = 400


class IncompleteApplication(DomainError):
    code = "Onboarding.IncompleteApplication"
    status_code = 400


class NoActiveWaiver(DomainError):
    code = "Onboarding.NoActiveWaiver"
    status_code = 500
