"""Parent billing use cases for autopay and checkout status."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import (
    AutopayConsentRepository,
    BillingSettingsRepository,
    ConnectedAccountRepository,
    EnrollmentAutopayStateRepository,
    ParentStripeCustomerRepository,
    PaymentRepository,
    StripeGateway,
    SubscriptionRepository,
    TransactionRunner,
)
from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed, PaymentNotFound
from backend.v2.contexts.billing.domain.events import (
    AutopayConsentCaptured,
    AutopayConsentCapturedPayload,
)
from backend.v2.contexts.billing.domain.models import AutopayConsent, Subscription
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

DEFAULT_CONSENT_TEXT_VERSION = "autopay-consent-v1"
DEFAULT_ACH_MANDATE_VERSION = "ach-mandate-v1"
DEFAULT_CARD_DISCLOSURE_VERSION = "card-disclosure-v1"


class StartSubscriptionCheckoutCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    enrollment_id: str
    session_id: str
    amount_cents: int = Field(gt=0)
    success_url: str
    cancel_url: str


class StartSubscriptionCheckoutResult(BaseModel):
    model_config = {"frozen": True}

    subscription_id: str
    checkout_session_id: str
    redirect_url: str


class CheckoutStatusResult(BaseModel):
    model_config = {"frozen": True}

    checkout_session_id: str
    payment_id: str | None = None
    status: str
    parent_id: str


class AutopaySetupCompletionResult(BaseModel):
    model_config = {"frozen": True}

    checkout_session_id: str | None = None
    setup_intent_id: str
    parent_id: str
    enrollment_id: str
    stripe_customer_id: str
    stripe_payment_method_id: str
    payment_method_type: str
    status: str = "active"
    payment_method_role: str = "primary"


class AutopayConsentCaptureContext(BaseModel):
    model_config = {"frozen": True}

    source: str = "unknown"
    actor_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None


class CompleteAutopaySetup:
    def __init__(
        self,
        *,
        stripe: StripeGateway,
        parent_customers: ParentStripeCustomerRepository,
        enrollment_autopay: EnrollmentAutopayStateRepository,
        consent_repo: AutopayConsentRepository | None = None,
        outbox: Outbox | None = None,
        transaction_runner: TransactionRunner | None = None,
        academy_id: str,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._stripe = stripe
        self._parent_customers = parent_customers
        self._enrollment_autopay = enrollment_autopay
        self._consent_repo = consent_repo
        self._outbox = outbox
        self._transaction_runner = transaction_runner
        self._academy_id = academy_id
        self._now = clock

    async def execute_from_checkout(
        self,
        checkout: dict[str, Any],
        *,
        expected_parent_id: str | None = None,
        consent_context: AutopayConsentCaptureContext | None = None,
    ) -> AutopaySetupCompletionResult:
        setup_intent_id = _stripe_id(checkout.get("setup_intent"))
        if not setup_intent_id:
            raise ValueError("autopay setup checkout missing setup_intent")
        setup_intent = await self._stripe.retrieve_setup_intent(setup_intent_id)
        return await self.execute_from_setup_intent(
            setup_intent,
            checkout_metadata=_string_metadata(checkout.get("metadata")),
            checkout_session_id=_stripe_id(checkout.get("id")),
            checkout_customer_id=_stripe_id(checkout.get("customer")),
            expected_parent_id=expected_parent_id,
            consent_context=consent_context,
        )

    async def execute_from_setup_intent(
        self,
        setup_intent: dict[str, Any],
        *,
        checkout_metadata: dict[str, str] | None = None,
        checkout_session_id: str | None = None,
        checkout_customer_id: str | None = None,
        expected_parent_id: str | None = None,
        consent_context: AutopayConsentCaptureContext | None = None,
    ) -> AutopaySetupCompletionResult:
        setup_metadata = _string_metadata(setup_intent.get("metadata"))
        checkout_metadata = checkout_metadata or {}
        for key in ("source", "academy_id", "parent_id", "enrollment_id", "payment_method_role"):
            setup_value = setup_metadata.get(key)
            checkout_value = checkout_metadata.get(key)
            if setup_value and checkout_value and setup_value != checkout_value:
                raise ValueError(
                    f"autopay setup metadata mismatch for {key}: "
                    f"setup_intent={setup_value} checkout={checkout_value}"
                )
        metadata = setup_metadata | checkout_metadata
        if metadata.get("source") != "autopay_setup":
            raise ValueError("setup completion is not for autopay_setup")
        academy_id = metadata.get("academy_id")
        if academy_id != self._academy_id:
            raise ValueError(
                f"autopay setup academy mismatch: event={academy_id} expected={self._academy_id}"
            )
        parent_id = metadata.get("parent_id")
        if not parent_id:
            raise ValueError("autopay setup missing parent_id")
        if expected_parent_id is not None and parent_id != expected_parent_id:
            raise PaymentNotFound(
                "checkout session not found",
                checkout_session_id=checkout_session_id,
            )
        enrollment_id = metadata.get("enrollment_id")
        if not enrollment_id:
            raise ValueError("autopay setup missing enrollment_id")
        setup_intent_id = _stripe_id(setup_intent.get("id"))
        if not setup_intent_id:
            raise ValueError("autopay setup missing setup_intent id")
        stripe_customer_id = _stripe_id(setup_intent.get("customer")) or checkout_customer_id
        if not stripe_customer_id:
            raise ValueError("autopay setup missing Stripe customer")
        stripe_payment_method_id = _stripe_id(setup_intent.get("payment_method"))
        if not stripe_payment_method_id:
            raise ValueError("autopay setup missing payment method")
        payment_method = await self._stripe.retrieve_payment_method(stripe_payment_method_id)
        payment_method_type = str(payment_method.get("type") or "unknown")
        payment_method_label, payment_method_last4 = _payment_method_display_details(payment_method)
        stripe_mandate_id = _stripe_id(setup_intent.get("mandate"))
        setup_status = _setup_status_for_payment_method(
            setup_intent=setup_intent,
            payment_method_type=payment_method_type,
        )
        payment_method_role = _payment_method_role(metadata.get("payment_method_role"))
        completed_at = self._now()
        consent = self._build_consent(
            parent_id=parent_id,
            enrollment_id=enrollment_id,
            setup_intent_id=setup_intent_id,
            checkout_session_id=checkout_session_id,
            stripe_payment_method_id=stripe_payment_method_id,
            payment_method_type=payment_method_type,
            metadata=metadata,
            captured_at=completed_at,
            context=consent_context,
        )

        should_activate = setup_status == "active" and payment_method_role == "primary"
        await self._persist_completion(
            parent_id=parent_id,
            enrollment_id=enrollment_id,
            stripe_customer_id=stripe_customer_id,
            stripe_payment_method_id=stripe_payment_method_id,
            payment_method_type=payment_method_type,
            stripe_mandate_id=stripe_mandate_id,
            setup_intent_id=setup_intent_id,
            checkout_session_id=checkout_session_id,
            completed_at=completed_at,
            consent=consent,
            setup_status=setup_status,
            payment_method_role=payment_method_role,
            payment_method_label=payment_method_label,
            payment_method_last4=payment_method_last4,
            activate_enrollment=False,
        )
        if should_activate:
            await self._stripe.set_customer_default_payment_method(
                stripe_customer_id=stripe_customer_id,
                stripe_payment_method_id=stripe_payment_method_id,
                metadata={
                    "academy_id": self._academy_id,
                    "parent_id": parent_id,
                },
            )
            await self._parent_customers.promote_payment_method_to_default(
                parent_id=parent_id,
                stripe_payment_method_id=stripe_payment_method_id,
                payment_method_type=payment_method_type,
                stripe_mandate_id=stripe_mandate_id,
                payment_method_label=payment_method_label,
                payment_method_last4=payment_method_last4,
            )
            activated = await self._enrollment_autopay.mark_autopay_active_from_setup(
                enrollment_id=enrollment_id,
            )
            if not activated:
                raise RuntimeError(
                    f"autopay enrollment activation failed for enrollment {enrollment_id}"
                )
        return AutopaySetupCompletionResult(
            checkout_session_id=checkout_session_id,
            setup_intent_id=setup_intent_id,
            parent_id=parent_id,
            enrollment_id=enrollment_id,
            stripe_customer_id=stripe_customer_id,
            stripe_payment_method_id=stripe_payment_method_id,
            payment_method_type=payment_method_type,
            status=setup_status,
            payment_method_role=payment_method_role,
        )

    async def _persist_completion(
        self,
        *,
        parent_id: str,
        enrollment_id: str,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        payment_method_type: str,
        stripe_mandate_id: str | None,
        setup_intent_id: str,
        checkout_session_id: str | None,
        completed_at: datetime,
        consent: AutopayConsent | None,
        setup_status: str = "active",
        payment_method_role: str = "primary",
        payment_method_label: str | None = None,
        payment_method_last4: str | None = None,
        activate_enrollment: bool = True,
    ) -> None:
        async def work(session: Any | None) -> None:
            persisted_consent = consent
            inserted_consent = False
            if consent is not None:
                persisted_consent = await self._consent_repo.append(  # type: ignore[union-attr]
                    consent,
                    session=session,
                )
                inserted_consent = persisted_consent.consent_id == consent.consent_id
                if inserted_consent and self._outbox is not None:
                    await self._outbox.append(
                        self._consent_event(persisted_consent),
                        session=session,
                    )
            await self._parent_customers.set_default_payment_method(
                parent_id=parent_id,
                stripe_customer_id=stripe_customer_id,
                stripe_payment_method_id=stripe_payment_method_id,
                payment_method_type=payment_method_type,
                stripe_mandate_id=stripe_mandate_id,
                setup_intent_id=setup_intent_id,
                checkout_session_id=checkout_session_id,
                completed_at=completed_at,
                current_consent_id=persisted_consent.consent_id if persisted_consent else None,
                consent_text_version=(
                    persisted_consent.consent_text_version if persisted_consent else None
                ),
                ach_mandate_version=(
                    persisted_consent.ach_mandate_version if persisted_consent else None
                ),
                card_disclosure_version=(
                    persisted_consent.card_disclosure_version if persisted_consent else None
                ),
                setup_status=setup_status,
                payment_method_role=payment_method_role,
                payment_method_label=payment_method_label,
                payment_method_last4=payment_method_last4,
                session=session,
            )
            if (
                activate_enrollment
                and setup_status == "active"
                and payment_method_role == "primary"
            ):
                activated = await self._enrollment_autopay.mark_autopay_active_from_setup(
                    enrollment_id=enrollment_id,
                    session=session,
                )
                if not activated:
                    raise RuntimeError(
                        f"autopay enrollment activation failed for enrollment {enrollment_id}"
                    )

        if self._transaction_runner is not None:
            await self._transaction_runner.run(work)
        else:
            await work(None)

    def _consent_event(self, consent: AutopayConsent) -> AutopayConsentCaptured:
        return AutopayConsentCaptured(
            aggregate_id=consent.consent_id,
            academy_id=self._academy_id,
            occurred_at=consent.captured_at,
            payload=AutopayConsentCapturedPayload(
                consent_id=consent.consent_id,
                parent_id=consent.parent_id,
                method_type=consent.method_type,
                consent_text_version=consent.consent_text_version,
                ach_mandate_version=consent.ach_mandate_version,
                card_disclosure_version=consent.card_disclosure_version,
                source=consent.source,
                actor_id=consent.actor_id,
                captured_at=consent.captured_at,
            ),
        )

    def _build_consent(
        self,
        *,
        parent_id: str,
        enrollment_id: str,
        setup_intent_id: str,
        checkout_session_id: str | None,
        stripe_payment_method_id: str,
        payment_method_type: str,
        metadata: dict[str, str],
        captured_at: datetime,
        context: AutopayConsentCaptureContext | None,
    ) -> AutopayConsent | None:
        if self._consent_repo is None:
            return None
        context = context or AutopayConsentCaptureContext(source="stripe_webhook")
        consent_text_version = metadata.get("consent_text_version") or DEFAULT_CONSENT_TEXT_VERSION
        is_ach = payment_method_type in {"us_bank_account", "ach"}
        ach_mandate_version = (
            metadata.get("ach_mandate_version") or DEFAULT_ACH_MANDATE_VERSION if is_ach else None
        )
        card_disclosure_version = (
            None
            if is_ach
            else metadata.get("card_disclosure_version") or DEFAULT_CARD_DISCLOSURE_VERSION
        )
        return AutopayConsent(
            consent_id=str(new_ulid()),
            academy_id=self._academy_id,
            parent_id=parent_id,
            enrollment_id=enrollment_id,
            setup_intent_id=setup_intent_id,
            checkout_session_id=checkout_session_id,
            stripe_payment_method_id=stripe_payment_method_id,
            method_type=payment_method_type,
            consent_text_version=consent_text_version,
            ach_mandate_version=ach_mandate_version,
            card_disclosure_version=card_disclosure_version,
            source=context.source,  # type: ignore[arg-type]
            actor_id=context.actor_id or parent_id,
            ip=context.ip,
            user_agent=context.user_agent,
            captured_at=captured_at,
            created_at=captured_at,
        )


class StartSubscriptionCheckout:
    def __init__(
        self,
        *,
        subscriptions: SubscriptionRepository,
        stripe: StripeGateway,
        academy_id: str,
        connected_accounts: ConnectedAccountRepository | None = None,
        settings: BillingSettingsRepository | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._subscriptions = subscriptions
        self._stripe = stripe
        self._academy_id = academy_id
        self._connected_accounts = connected_accounts
        self._settings = settings
        self._now = clock

    async def execute(
        self, cmd: StartSubscriptionCheckoutCommand
    ) -> StartSubscriptionCheckoutResult:
        connected_account_id = await self._ready_connected_account_id()
        existing = await self._subscriptions.latest_for_enrollment(cmd.enrollment_id)
        if (
            self._connected_accounts is None
            and existing is not None
            and existing.parent_id == cmd.parent_id
            and existing.status == "incomplete"
            and existing.stripe_checkout_session_id
        ):
            checkout = await self._stripe.retrieve_checkout_session(
                existing.stripe_checkout_session_id
            )
            checkout_status = str(checkout.get("status") or "")
            checkout_url = str(checkout.get("url") or "")
            if checkout_status == "open" and checkout_url:
                return StartSubscriptionCheckoutResult(
                    subscription_id=existing.subscription_id,
                    checkout_session_id=existing.stripe_checkout_session_id,
                    redirect_url=checkout_url,
                )
            if checkout_status == "complete":
                return StartSubscriptionCheckoutResult(
                    subscription_id=existing.subscription_id,
                    checkout_session_id=existing.stripe_checkout_session_id,
                    redirect_url=_success_url_with_checkout_session(
                        cmd.success_url,
                        existing.stripe_checkout_session_id,
                    ),
                )

        subscription_id = str(new_ulid())
        success_url = _success_url_with_checkout_session_placeholder(cmd.success_url)
        try:
            checkout_id, url = await self._stripe.create_autopay_setup_checkout_session(
                parent_id=cmd.parent_id,
                enrollment_id=cmd.enrollment_id,
                session_id=cmd.session_id,
                success_url=success_url,
                cancel_url=cmd.cancel_url,
                metadata={
                    "academy_id": self._academy_id,
                    "app_subscription_id": subscription_id,
                    # Legacy key retained so older deployed code and any
                    # already-created Checkout Sessions keep reconciling.
                    "subscription_id": subscription_id,
                    "parent_id": cmd.parent_id,
                    "enrollment_id": cmd.enrollment_id,
                    "session_id": cmd.session_id,
                    "source": "autopay_setup",
                    "consent_text_version": DEFAULT_CONSENT_TEXT_VERSION,
                    "ach_mandate_version": DEFAULT_ACH_MANDATE_VERSION,
                    "card_disclosure_version": DEFAULT_CARD_DISCLOSURE_VERSION,
                },
                connected_account_id=connected_account_id,
            )
        except Exception as exc:  # pragma: no cover - infra path
            raise CheckoutCreationFailed(str(exc)) from exc

        return StartSubscriptionCheckoutResult(
            subscription_id=subscription_id,
            checkout_session_id=checkout_id,
            redirect_url=url,
        )

    async def _ready_connected_account_id(self) -> str | None:
        if self._connected_accounts is None:
            return None
        account = await self._connected_accounts.get_for_academy()
        if account is None or not account.is_ready_for_charges():
            if await self._platform_fallback_enabled():
                log.warning(
                    "start_subscription_checkout: connected account not ready — falling back "
                    "to PLATFORM charge (allow_platform_charge_fallback=on)"
                )
                return None
            raise CheckoutCreationFailed("Stripe connected account is not ready for autopay setup.")
        return account.stripe_account_id

    async def _platform_fallback_enabled(self) -> bool:
        if self._settings is None:
            return False
        try:
            settings = await self._settings.get()
        except Exception as exc:
            log.warning(
                "start_subscription_checkout: billing settings lookup failed; keeping "
                "fail-closed connected-account requirement err=%s",
                exc,
            )
            return False
        return settings.allow_platform_charge_fallback


class CreateCustomerPortalSessionCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    return_url: str
    stripe_customer_id: str | None = None


class CreateCustomerPortalSessionResult(BaseModel):
    model_config = {"frozen": True}

    redirect_url: str


class CreateCustomerPortalSession:
    def __init__(self, *, stripe: StripeGateway) -> None:
        self._stripe = stripe

    async def execute(
        self, cmd: CreateCustomerPortalSessionCommand
    ) -> CreateCustomerPortalSessionResult:
        try:
            url = await self._stripe.create_customer_portal_session(
                parent_id=cmd.parent_id,
                return_url=cmd.return_url,
                stripe_customer_id=cmd.stripe_customer_id,
            )
        except Exception as exc:  # pragma: no cover - infra path
            raise CheckoutCreationFailed(str(exc)) from exc
        return CreateCustomerPortalSessionResult(redirect_url=url)


class GetCheckoutStatus:
    def __init__(
        self,
        *,
        payments: PaymentRepository,
        subscriptions: SubscriptionRepository | None = None,
        stripe: StripeGateway | None = None,
        parent_customers: ParentStripeCustomerRepository | None = None,
        enrollment_autopay: EnrollmentAutopayStateRepository | None = None,
        consent_repo: AutopayConsentRepository | None = None,
        outbox: Outbox | None = None,
        transaction_runner: TransactionRunner | None = None,
        academy_id: str | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._payments = payments
        self._subscriptions = subscriptions
        self._stripe = stripe
        self._parent_customers = parent_customers
        self._enrollment_autopay = enrollment_autopay
        self._consent_repo = consent_repo
        self._outbox = outbox
        self._transaction_runner = transaction_runner
        self._academy_id = academy_id
        self._now = clock

    async def execute(
        self,
        checkout_session_id: str,
        *,
        parent_id: str,
        consent_context: AutopayConsentCaptureContext | None = None,
    ) -> CheckoutStatusResult:
        payment = await self._payments.get_by_checkout_session(checkout_session_id)
        if payment is not None:
            if payment.parent_id != parent_id:
                raise PaymentNotFound(
                    "checkout session not found",
                    checkout_session_id=checkout_session_id,
                )
            return CheckoutStatusResult(
                checkout_session_id=checkout_session_id,
                payment_id=payment.payment_id,
                status=payment.status,
                parent_id=payment.parent_id,
            )
        subscription = None
        if self._subscriptions is not None:
            subscription = await self._subscriptions.get_by_checkout_session(checkout_session_id)
        if subscription is None and self._stripe is not None:
            checkout = await self._stripe.retrieve_checkout_session(checkout_session_id)
            if _is_autopay_setup_checkout(checkout):
                return await self._status_from_autopay_setup_checkout(
                    checkout,
                    expected_parent_id=parent_id,
                    consent_context=consent_context,
                )
        if subscription is None:
            raise PaymentNotFound(
                "checkout session not found",
                checkout_session_id=checkout_session_id,
            )
        if subscription.parent_id != parent_id:
            raise PaymentNotFound(
                "checkout session not found",
                checkout_session_id=checkout_session_id,
            )
        if self._stripe is not None and subscription.status == "incomplete":
            checkout = await self._stripe.retrieve_checkout_session(checkout_session_id)
            if _is_autopay_setup_checkout(checkout):
                return await self._status_from_autopay_setup_checkout(
                    checkout,
                    expected_parent_id=parent_id,
                    consent_context=consent_context,
                )
            subscription = await self._reconcile_subscription_checkout(subscription, checkout)
        return CheckoutStatusResult(
            checkout_session_id=checkout_session_id,
            payment_id=None,
            status=subscription.status,
            parent_id=subscription.parent_id,
        )

    async def _status_from_autopay_setup_checkout(
        self,
        checkout: dict[str, Any],
        *,
        expected_parent_id: str,
        consent_context: AutopayConsentCaptureContext | None = None,
    ) -> CheckoutStatusResult:
        checkout_id = _stripe_id(checkout.get("id")) or ""
        checkout_parent_id = _checkout_parent_id(checkout)
        if checkout_parent_id != expected_parent_id:
            raise PaymentNotFound("checkout session not found", checkout_session_id=checkout_id)
        status = str(checkout.get("status") or "")
        if status != "complete":
            return CheckoutStatusResult(
                checkout_session_id=checkout_id,
                payment_id=None,
                status=status or "pending",
                parent_id=expected_parent_id,
            )
        if (
            self._stripe is None
            or self._parent_customers is None
            or self._enrollment_autopay is None
            or self._academy_id is None
        ):
            raise ValueError("autopay setup completion dependencies are not configured")
        result = await CompleteAutopaySetup(
            stripe=self._stripe,
            parent_customers=self._parent_customers,
            enrollment_autopay=self._enrollment_autopay,
            consent_repo=self._consent_repo,
            outbox=self._outbox,
            transaction_runner=self._transaction_runner,
            academy_id=self._academy_id,
            clock=self._now,
        ).execute_from_checkout(
            checkout,
            expected_parent_id=expected_parent_id,
            consent_context=consent_context,
        )
        return CheckoutStatusResult(
            checkout_session_id=checkout_id,
            payment_id=None,
            status=result.status,
            parent_id=result.parent_id,
        )

    async def _reconcile_subscription_checkout(
        self,
        subscription: Subscription,
        checkout: dict[str, object],
    ) -> Subscription:
        status = str(checkout.get("status") or "")
        stripe_subscription_id = str(checkout.get("subscription") or "")
        metadata = checkout.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        is_setup_checkout = (
            str(checkout.get("mode") or "") == "setup"
            or str(metadata.get("source") or "") == "autopay_setup"
        )
        if status != "complete":
            return subscription
        if not stripe_subscription_id and not is_setup_checkout:
            return subscription
        updated = subscription.model_copy(
            update={
                "stripe_subscription_id": stripe_subscription_id,
                "status": "active",
                "updated_at": self._now(),
            }
        )
        await self._subscriptions.save(updated)  # type: ignore[union-attr]
        stripe_customer_id = str(checkout.get("customer") or "")
        if self._parent_customers is not None and stripe_customer_id:
            await self._parent_customers.set_stripe_customer_id(
                parent_id=updated.parent_id,
                stripe_customer_id=stripe_customer_id,
            )
        if self._enrollment_autopay is not None and updated.enrollment_id:
            await self._enrollment_autopay.mark_autopay_active_from_setup(
                enrollment_id=updated.enrollment_id,
            )
        return updated


def _success_url_with_checkout_session_placeholder(success_url: str) -> str:
    if "checkout_session_id=" in success_url:
        return success_url
    separator = "&" if "?" in success_url else "?"
    return f"{success_url}{separator}checkout_session_id={{CHECKOUT_SESSION_ID}}"


def _success_url_with_checkout_session(success_url: str, checkout_session_id: str) -> str:
    with_placeholder = _success_url_with_checkout_session_placeholder(success_url)
    return with_placeholder.replace("{CHECKOUT_SESSION_ID}", checkout_session_id)


def _string_metadata(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if v is not None}


def _stripe_id(value: object) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        object_id = value.get("id")
        return str(object_id) if object_id else None
    return None


def _payment_method_role(value: object) -> str:
    role = str(value or "primary").strip().lower()
    return role if role in {"primary", "fallback"} else "primary"


def _setup_status_for_payment_method(
    *,
    setup_intent: dict[str, Any],
    payment_method_type: str,
) -> str:
    if payment_method_type != "us_bank_account":
        return "active"
    status = str(setup_intent.get("status") or "")
    if not status:
        return "active"
    next_action = setup_intent.get("next_action")
    next_action_type = ""
    if isinstance(next_action, dict):
        next_action_type = str(next_action.get("type") or "")
    if status == "succeeded":
        return "active"
    if next_action_type == "verify_with_microdeposits" or status == "requires_action":
        return "verification_required"
    return "verification_pending"


def _payment_method_display_details(
    payment_method: dict[str, Any],
) -> tuple[str | None, str | None]:
    payment_method_type = str(payment_method.get("type") or "")
    if payment_method_type == "card":
        card = payment_method.get("card")
        if not isinstance(card, dict):
            return None, None
        brand = str(card.get("brand") or "").strip()
        label = brand.title() if brand else "Card"
        return label, _last4(card.get("last4"))
    if payment_method_type == "us_bank_account":
        bank = payment_method.get("us_bank_account")
        if not isinstance(bank, dict):
            return None, None
        bank_name = str(bank.get("bank_name") or "").strip()
        last4 = _last4(bank.get("last4"))
        if bank_name:
            return bank_name, last4
        if last4:
            return "Bank account", last4
        return None, None
    return None, None


def _last4(value: object) -> str | None:
    text = str(value or "").strip()
    if len(text) == 4 and text.isdigit():
        return text
    return None


def _is_autopay_setup_checkout(checkout: dict[str, Any]) -> bool:
    metadata = _string_metadata(checkout.get("metadata"))
    return str(checkout.get("mode") or "") == "setup" or metadata.get("source") == "autopay_setup"


def _checkout_parent_id(checkout: dict[str, Any]) -> str | None:
    metadata = _string_metadata(checkout.get("metadata"))
    parent_id = metadata.get("parent_id")
    if parent_id:
        return parent_id
    client_reference_id = checkout.get("client_reference_id")
    return str(client_reference_id) if client_reference_id else None
