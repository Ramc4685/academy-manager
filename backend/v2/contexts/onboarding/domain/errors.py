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


class ApplicationForPaymentNotFound(DomainError):
    """No onboarding application claims this payment id.

    Raised (never returned as ``None``) by ``TransitionApplication`` so the miss
    can never be mistaken for "handled". For a registration checkout it means a
    parent may have been charged with nothing left to advance, which is an alert
    path; for a payment that never had an onboarding context — an invoice, a
    subscription, an admin-recorded payment — it is the expected benign case and
    the cross-context handler says so explicitly (#549).
    """

    code = "Onboarding.ApplicationForPaymentNotFound"
    status_code = 404
