"""Billing domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class InvalidWebhookSignature(DomainError):
    code = "Billing.InvalidWebhookSignature"
    status_code = 400


class PaymentNotFound(DomainError):
    code = "Billing.PaymentNotFound"
    status_code = 404


class SubscriptionNotFound(DomainError):
    code = "Billing.SubscriptionNotFound"
    status_code = 404


class RefundExceedsAmount(DomainError):
    code = "Billing.RefundExceedsAmount"
    status_code = 400


class RefundFailed(DomainError):
    code = "Billing.RefundFailed"
    status_code = 502


class CheckoutCreationFailed(DomainError):
    code = "Billing.CheckoutCreationFailed"
    status_code = 502


class PaymentOperationNotAllowed(DomainError):
    code = "Billing.PaymentOperationNotAllowed"
    status_code = 400


class SessionTypeNotFound(DomainError):
    code = "Billing.SessionTypeNotFound"
    status_code = 404


class StudentBillingEnrollmentNotFound(DomainError):
    code = "Billing.StudentBillingEnrollmentNotFound"
    status_code = 404


class SessionTypeInactive(DomainError):
    code = "Billing.SessionTypeInactive"
    status_code = 400


class AcademyMismatchError(DomainError):
    """Raised when a use case's bound academy_id does not match the academy_id
    supplied by the caller (e.g. a route path param). Maps to 404, matching
    ``require_platform_admin``'s convention for authz-adjacent failures: it
    must not confirm or deny to an unauthorized caller whether the target
    academy exists."""

    code = "Billing.AcademyMismatch"
    status_code = 404
