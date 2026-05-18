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


class MissingSelectedSession(DomainError):
    code = "Onboarding.MissingSelectedSession"
    status_code = 422


class NoActiveWaiver(DomainError):
    code = "Onboarding.NoActiveWaiver"
    status_code = 500


class ApplicationOwnedByAnotherParent(DomainError):
    """Returned as 404 (not 403) so a parent can't probe the existence
    of another parent's application id."""

    code = "Onboarding.ApplicationNotFound"
    status_code = 404
