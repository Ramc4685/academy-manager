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


class InvoicePayLinkUnavailable(DomainError):
    """A parent asked to pay an open invoice but no Stripe Checkout URL could be
    produced — the gateway raised, or funds cannot be routed to the academy's
    connected account (issue #426).

    409 (not 502) preserves the status the parent portal's "Pay now" flow has
    always returned for an unusable invoice; the ``code`` is what is new, so the
    frontend payment-error mapper can render a real explanation instead of a
    generic "something went wrong".
    """

    code = "Billing.InvoicePayLinkUnavailable"
    status_code = 409


class ConnectOnboardingFailed(DomainError):
    code = "Billing.ConnectOnboardingFailed"
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


class AutopayActivationFailed(DomainError):
    """Autopay setup completed at Stripe (payment method saved) but the
    enrollment's autopay state could not be activated — the projection doc is
    missing and could not be reconstructed from the legacy enrollment. 409 so
    the checkout-status poll gets a structured, non-5xx error instead of an
    unhandled RuntimeError (2026-07-04 incident)."""

    code = "Billing.AutopayActivationFailed"
    status_code = 409


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
