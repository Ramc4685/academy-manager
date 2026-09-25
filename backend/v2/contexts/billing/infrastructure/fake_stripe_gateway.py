"""Fake StripeGateway for dev/test.

Records calls; returns deterministic IDs. Real Stripe stays out of CI.

Account dimension (mirrors Stripe): every Checkout Session, Customer,
PaymentIntent, SetupIntent and PaymentMethod the fake mints is owned by the
account it was created on (``stripe_account``; ``None`` = the platform).
Using that id with any OTHER account raises ``StripeResourceNotFound`` — the
fake's ``resource_missing``. Ids the fake never minted are accepted on the
platform only (legacy tests pass hand-written platform ids); on a connected
account an unknown id is missing, exactly as Stripe would answer. Tests seed
objects that live on a connected account with :meth:`register_object` /
:meth:`seed_saved_card`.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.v2.contexts.billing.application.ports import (
    StripeCheckoutSessionNotExpirable,
    StripeGateway,
    StripeResourceNotFound,
)
from backend.v2.contexts.billing.domain.fees import check_application_fee_cents
from backend.v2.shared.ids import new_ulid

_PLATFORM_CUSTOMER_ID = "cus_fake_parent"


class FakeStripeGateway(StripeGateway):
    def __init__(self) -> None:
        # object id -> the account that owns it (None = platform).
        self._owners: dict[str, str | None] = {_PLATFORM_CUSTOMER_ID: None}
        # (stripe_account, academy_id, parent_id) -> (customer_id, pm_id): the
        # saved card ``get_default_payment_method`` finds by Customer search.
        self.saved_cards: dict[tuple[str | None, str, str], tuple[str, str]] = {}
        # PaymentIntents the fake knows in full, by id.
        self._payment_intents_by_id: dict[str, dict[str, Any]] = {}
        self.invoice_checkouts: list[dict[str, Any]] = []
        self.checkouts: list[dict[str, Any]] = []
        self.subscription_checkouts: list[dict[str, Any]] = []
        self.autopay_setup_checkouts: list[dict[str, Any]] = []
        self.portal_sessions: list[dict[str, Any]] = []
        self.refunds: list[dict[str, Any]] = []
        # Every refund create call, including idempotent replays Stripe answers
        # with the original refund (those add nothing to ``refunds``).
        self.refund_requests: list[dict[str, Any]] = []
        self._refunds_by_key: dict[str, dict[str, Any]] = {}
        self.cancelled_subscriptions: list[dict[str, Any]] = []
        self.paused_subscriptions: list[dict[str, Any]] = []
        self.resumed_subscriptions: list[dict[str, Any]] = []
        self.subscription_prorations: list[dict[str, Any]] = []
        self.connect_links: list[dict[str, str]] = []
        self.connect_codes: list[str] = []
        # Slice I — Connect (Accounts v2 + destination charges).
        self.connected_accounts: list[dict[str, Any]] = []
        self.account_onboarding_links: list[dict[str, Any]] = []
        # stripe_account_id -> v1 Account snapshot returned by
        # retrieve_connected_account; unknown ids read as not yet onboarded.
        self.account_snapshots: dict[str, dict[str, Any]] = {}
        self.retrieved_connected_accounts: list[str] = []
        self.off_session_payment_intents: list[dict[str, Any]] = []
        self.payment_intents: list[dict[str, Any]] = []
        self.setup_intents: dict[str, dict[str, Any]] = {}
        self.payment_methods: dict[str, dict[str, Any]] = {}
        self.customer_default_payment_methods: list[dict[str, Any]] = []
        # customer_id -> list of charge dicts (legacy match candidates, #242 WI-3)
        self.charges_by_customer: dict[str, list[dict[str, Any]]] = {}
        # stripe_account -> extra PaymentIntents only visible when a
        # reconciliation search is scoped to that connected account (Slice I).
        self.connected_payment_intents: dict[str, list[dict[str, Any]]] = {}
        # Checkout sessions retired by a supersede.
        self.expired_checkouts: list[str] = []
        # Ids that refuse to expire, mirroring Stripe's behaviour for a session
        # that is already complete or expired. Tests add to this to exercise
        # the "parent paid on the old tab" race.
        self.unexpirable_checkouts: set[str] = set()
        # Stripe Invoicing invoices voided alongside a ledger void (#784).
        self.voided_invoices: list[str] = []

    # -- account dimension -------------------------------------------------

    def register_object(self, object_id: str, *, stripe_account: str | None = None) -> None:
        """Declare that ``object_id`` lives on ``stripe_account`` (None = platform)."""
        self._owners[object_id] = stripe_account

    def seed_saved_card(
        self,
        *,
        academy_id: str,
        parent_id: str,
        customer_id: str,
        payment_method_id: str,
        stripe_account: str | None = None,
    ) -> None:
        """A parent's saved default card on ``stripe_account`` (None = platform)."""
        self.register_object(customer_id, stripe_account=stripe_account)
        self.register_object(payment_method_id, stripe_account=stripe_account)
        self.saved_cards[(stripe_account, academy_id, parent_id)] = (
            customer_id,
            payment_method_id,
        )

    def account_of(self, object_id: str) -> str | None:
        return self._owners.get(object_id)

    def _require_on_account(self, object_id: str, stripe_account: str | None, kind: str) -> None:
        """Stripe answers ``resource_missing`` for an id used on the wrong account."""
        if object_id in self._owners:
            if self._owners[object_id] == stripe_account:
                return
        elif stripe_account is None:
            # Never minted by the fake: a hand-written platform id (legacy tests).
            return
        where = stripe_account or "the platform account"
        raise StripeResourceNotFound(f"No such {kind}: '{object_id}' on {where}")

    def _customer_id_for(self, stripe_account: str | None) -> str:
        if stripe_account is None:
            return _PLATFORM_CUSTOMER_ID
        customer_id = f"{_PLATFORM_CUSTOMER_ID}_{stripe_account}"
        self.register_object(customer_id, stripe_account=stripe_account)
        return customer_id

    # -- checkout ------------------------------------------------------------

    async def create_checkout_session(
        self,
        *,
        parent_id: str,
        session_id: str,
        amount_cents: int,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
        connected_account_id: str | None = None,
        application_fee_cents: int = 0,
        stripe_account: str | None = None,
    ) -> tuple[str, str]:
        # Same validation as the real gateway, so a test cannot pass with a fee
        # Stripe (or RealStripeGateway) would refuse.
        _check_single_route(connected_account_id, stripe_account)
        check_application_fee_cents(
            fee_cents=application_fee_cents,
            amount_cents=amount_cents,
            connected_account_id=connected_account_id or stripe_account,
        )
        checkout_id = f"cs_test_{new_ulid()}"
        self.register_object(checkout_id, stripe_account=stripe_account)
        record = {
            "checkout_id": checkout_id,
            "parent_id": parent_id,
            "session_id": session_id,
            "amount_cents": amount_cents,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": metadata,
            "connected_account_id": connected_account_id,
            "application_fee_amount": (
                application_fee_cents if (connected_account_id or stripe_account) else None
            ),
            "stripe_account": stripe_account,
        }
        self.checkouts.append(record)
        return checkout_id, f"https://fake.stripe.com/c/{checkout_id}"

    async def create_subscription_checkout_session(
        self,
        *,
        parent_id: str,
        enrollment_id: str,
        session_id: str,
        amount_cents: int,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
        stripe_account: str | None = None,
    ) -> tuple[str, str, str]:
        checkout_id = f"cs_sub_test_{new_ulid()}"
        stripe_subscription_id = f"sub_test_{new_ulid()}"
        self.register_object(checkout_id, stripe_account=stripe_account)
        self.register_object(stripe_subscription_id, stripe_account=stripe_account)
        self.subscription_checkouts.append(
            {
                "checkout_id": checkout_id,
                "stripe_subscription_id": stripe_subscription_id,
                "parent_id": parent_id,
                "enrollment_id": enrollment_id,
                "session_id": session_id,
                "amount_cents": amount_cents,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata,
                "stripe_account": stripe_account,
            }
        )
        return checkout_id, f"https://fake.stripe.com/c/{checkout_id}", stripe_subscription_id

    async def create_autopay_setup_checkout_session(
        self,
        *,
        parent_id: str,
        enrollment_id: str,
        session_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
        connected_account_id: str | None = None,
        stripe_account: str | None = None,
    ) -> tuple[str, str]:
        _check_single_route(connected_account_id, stripe_account)
        checkout_id = f"cs_setup_test_{new_ulid()}"
        setup_intent_id = f"seti_fake_{checkout_id}"
        payment_method_id = f"pm_fake_{checkout_id}"
        # Checkout customer_creation="always": the customer, the SetupIntent and
        # the saved payment method all live on the account the session is on.
        customer_id = self._customer_id_for(stripe_account)
        for object_id in (checkout_id, setup_intent_id, payment_method_id):
            self.register_object(object_id, stripe_account=stripe_account)
        self.autopay_setup_checkouts.append(
            {
                "checkout_id": checkout_id,
                "parent_id": parent_id,
                "enrollment_id": enrollment_id,
                "session_id": session_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata,
                "setup_intent_id": setup_intent_id,
                # Slice I: connected academy account the eventual off-session
                # charges route to (setup_intent_data.on_behalf_of).
                "connected_account_id": connected_account_id,
                "stripe_account": stripe_account,
                "customer_id": customer_id,
            }
        )
        self.setup_intents[setup_intent_id] = {
            "id": setup_intent_id,
            "object": "setup_intent",
            "customer": customer_id,
            "payment_method": payment_method_id,
            "mandate": f"mandate_fake_{checkout_id}",
            "metadata": dict(metadata),
        }
        self.payment_methods[payment_method_id] = {
            "id": payment_method_id,
            "object": "payment_method",
            "type": "card",
        }
        return checkout_id, f"https://fake.stripe.com/c/{checkout_id}"

    async def create_invoice_checkout_session(
        self,
        *,
        invoice_id: str,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
        idempotency_key: str | None = None,
        connected_account_id: str | None = None,
        save_payment_method_for_autopay: bool = False,
        autopay_enrollment_ids: list[str] | None = None,
        application_fee_cents: int = 0,
        stripe_account: str | None = None,
    ) -> tuple[str, str]:
        _check_single_route(connected_account_id, stripe_account)
        check_application_fee_cents(
            fee_cents=application_fee_cents,
            amount_cents=amount_cents,
            connected_account_id=connected_account_id or stripe_account,
        )
        # Stripe idempotency is per account: the same key on the same account
        # replays the original session.
        if idempotency_key is not None:
            for record in self.invoice_checkouts:
                if (
                    record["idempotency_key"] == idempotency_key
                    and record["stripe_account"] == stripe_account
                ):
                    return record["checkout_id"], record["url"]
        checkout_id = f"cs_inv_test_{new_ulid()}"
        self.register_object(checkout_id, stripe_account=stripe_account)
        url = f"https://fake.stripe.com/c/{checkout_id}"
        self.invoice_checkouts.append(
            {
                "checkout_id": checkout_id,
                "url": url,
                "invoice_id": invoice_id,
                "amount_cents": amount_cents,
                "currency": currency,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": dict(metadata),
                "idempotency_key": idempotency_key,
                "connected_account_id": connected_account_id,
                "save_payment_method_for_autopay": save_payment_method_for_autopay,
                "autopay_enrollment_ids": list(autopay_enrollment_ids or []),
                "application_fee_amount": (
                    application_fee_cents if (connected_account_id or stripe_account) else None
                ),
                "stripe_account": stripe_account,
                "parent_id": metadata.get("parent_id"),
            }
        )
        return checkout_id, url

    async def create_customer_portal_session(
        self,
        *,
        parent_id: str,
        return_url: str,
        stripe_customer_id: str | None,
        stripe_account: str | None = None,
    ) -> str:
        # Mirror RealStripeGateway: Stripe has no portal for a parent with no
        # customer, so the fake must not hand back a redirect URL either. A
        # permissive fake here made a local stack (no STRIPE_API_KEY ->
        # FakeStripeGateway) redirect to a nonexistent fake.stripe.com page
        # instead of showing the autopay prerequisite (issue #595).
        if not stripe_customer_id:
            raise ValueError(
                "Billing portal will be available after the first successful autopay setup."
            )
        self._require_on_account(stripe_customer_id, stripe_account, "customer")
        portal_id = f"bps_test_{new_ulid()}"
        self.portal_sessions.append(
            {
                "portal_id": portal_id,
                "parent_id": parent_id,
                "return_url": return_url,
                "stripe_customer_id": stripe_customer_id,
            }
        )
        return f"https://fake.stripe.com/portal/{portal_id}"

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, object]:
        # Tests pass already-parsed events as JSON body and a fixed sig.
        if signature != "test_signature":
            raise ValueError("invalid signature")
        return json.loads(payload.decode("utf-8"))

    async def retrieve_checkout_session(
        self, checkout_session_id: str, *, stripe_account: str | None = None
    ) -> dict[str, Any]:
        self._require_on_account(checkout_session_id, stripe_account, "checkout.session")
        for record in (
            self.subscription_checkouts
            + self.autopay_setup_checkouts
            + self.checkouts
            + self.invoice_checkouts
        ):
            if record["checkout_id"] == checkout_session_id:
                metadata = dict(record.get("metadata") or {})
                return {
                    "id": checkout_session_id,
                    "object": "checkout.session",
                    "status": "complete",
                    "payment_status": "paid",
                    "amount_total": record.get("amount_cents"),
                    "currency": "usd",
                    "customer": record.get("customer_id")
                    or self._customer_id_for(record.get("stripe_account")),
                    "subscription": record.get("stripe_subscription_id"),
                    "setup_intent": record.get(
                        "setup_intent_id", f"seti_fake_{checkout_session_id}"
                    ),
                    "invoice": f"in_fake_{checkout_session_id}",
                    "client_reference_id": record.get("parent_id"),
                    "metadata": metadata,
                }
        return {"id": checkout_session_id, "object": "checkout.session"}

    async def expire_checkout_session(
        self, checkout_session_id: str, *, stripe_account: str | None = None
    ) -> None:
        self._require_on_account(checkout_session_id, stripe_account, "checkout.session")
        if checkout_session_id in self.unexpirable_checkouts:
            # Mirrors the real gateway: "unexpirable" means already complete or
            # expired, which is the TERMINAL case callers may swallow. A generic
            # ValueError here would fake the transient case instead (#549).
            raise StripeCheckoutSessionNotExpirable(
                f"checkout session is not expirable: {checkout_session_id}"
            )
        self.expired_checkouts.append(checkout_session_id)

    async def retrieve_invoice(self, stripe_invoice_id: str) -> dict[str, Any]:
        return {
            "id": stripe_invoice_id,
            "object": "invoice",
            "status": "paid",
            "amount_paid": 0,
            "currency": "usd",
            "payment_intent": f"pi_fake_{stripe_invoice_id}",
        }

    async def void_stripe_invoice(self, stripe_invoice_id: str) -> None:
        self.voided_invoices.append(stripe_invoice_id)

    async def retrieve_subscription(self, stripe_subscription_id: str) -> dict[str, Any]:
        return {
            "id": stripe_subscription_id,
            "object": "subscription",
        }

    async def retrieve_payment_intent(
        self, stripe_payment_intent_id: str, *, stripe_account: str | None = None
    ) -> dict[str, Any]:
        self._require_on_account(stripe_payment_intent_id, stripe_account, "payment_intent")
        known = self._payment_intents_by_id.get(stripe_payment_intent_id)
        if known is not None:
            return dict(known)
        return {
            "id": stripe_payment_intent_id,
            "object": "payment_intent",
        }

    async def retrieve_setup_intent(
        self, stripe_setup_intent_id: str, *, stripe_account: str | None = None
    ) -> dict[str, Any]:
        self._require_on_account(stripe_setup_intent_id, stripe_account, "setup_intent")
        return self.setup_intents.get(
            stripe_setup_intent_id,
            {
                "id": stripe_setup_intent_id,
                "object": "setup_intent",
                "customer": "cus_fake_parent",
                "payment_method": f"pm_fake_{stripe_setup_intent_id}",
                "metadata": {},
            },
        )

    async def retrieve_payment_method(
        self, stripe_payment_method_id: str, *, stripe_account: str | None = None
    ) -> dict[str, Any]:
        self._require_on_account(stripe_payment_method_id, stripe_account, "payment_method")
        return self.payment_methods.get(
            stripe_payment_method_id,
            {
                "id": stripe_payment_method_id,
                "object": "payment_method",
                "type": "card",
            },
        )

    async def set_customer_default_payment_method(
        self,
        *,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        metadata: dict[str, str],
        stripe_account: str | None = None,
    ) -> None:
        self._require_on_account(stripe_customer_id, stripe_account, "customer")
        self._require_on_account(stripe_payment_method_id, stripe_account, "payment_method")
        record: dict[str, Any] = {
            "stripe_customer_id": stripe_customer_id,
            "stripe_payment_method_id": stripe_payment_method_id,
            "metadata": metadata,
        }
        if stripe_account is not None:
            record["stripe_account"] = stripe_account
        self.customer_default_payment_methods.append(record)
        academy_id = str(metadata.get("academy_id") or "")
        parent_id = str(metadata.get("parent_id") or "")
        if academy_id and parent_id:
            self.saved_cards[(stripe_account, academy_id, parent_id)] = (
                stripe_customer_id,
                stripe_payment_method_id,
            )

    async def search_app_owned_payment_intents(
        self, *, academy_id: str, limit: int = 100, stripe_account: str | None = None
    ) -> list[dict[str, Any]]:
        source = (
            self.connected_payment_intents.get(stripe_account, [])
            if stripe_account
            else self.payment_intents
        )
        for pi in source:
            # PaymentIntents seeded per account live on that account.
            if pi.get("id") and str(pi["id"]) not in self._owners:
                self.register_object(str(pi["id"]), stripe_account=stripe_account or None)
        matched = [
            pi
            for pi in source
            if str((pi.get("metadata") or {}).get("academy_id") or "") == academy_id
            and str(pi.get("status") or "").lower() in {"succeeded", "processing"}
        ]
        return matched[: max(1, min(int(limit), 100))]

    async def list_charges_for_customer(
        self, *, stripe_customer_id: str, limit: int = 100, stripe_account: str | None = None
    ) -> list[dict[str, Any]]:
        self._require_on_account(stripe_customer_id, stripe_account, "customer")
        charges = self.charges_by_customer.get(stripe_customer_id, [])
        return charges[: max(1, min(int(limit), 100))]

    async def issue_refund(
        self,
        payment_intent_id: str,
        amount_cents: int | None,
        *,
        idempotency_key: str | None = None,
        stripe_account: str | None = None,
    ) -> str:
        # Mirrors Stripe's idempotency semantics: a repeat with the same key and
        # parameters returns the ORIGINAL refund (no second refund object); the
        # same key with different parameters is an error. Keys are scoped per
        # account, and a PaymentIntent is only refundable on its own account.
        self._require_on_account(payment_intent_id, stripe_account, "payment_intent")
        params = {"payment_intent_id": payment_intent_id, "amount_cents": amount_cents}
        request: dict[str, Any] = {**params, "idempotency_key": idempotency_key}
        if stripe_account is not None:
            request["stripe_account"] = stripe_account
        self.refund_requests.append(request)
        scoped_key = (
            None
            if idempotency_key is None
            else (
                idempotency_key if stripe_account is None else f"{stripe_account}:{idempotency_key}"
            )
        )
        if scoped_key is not None and scoped_key in self._refunds_by_key:
            original = self._refunds_by_key[scoped_key]
            if {k: original[k] for k in params} != params:
                raise RuntimeError(
                    "Keys for idempotent requests can only be used with the same "
                    "parameters they were first used with."
                )
            return str(original["refund_id"])
        refund_id = f"re_test_{new_ulid()}"
        refund = {**params, "refund_id": refund_id, "idempotency_key": idempotency_key}
        if stripe_account is not None:
            refund["stripe_account"] = stripe_account
        self.register_object(refund_id, stripe_account=stripe_account)
        self.refunds.append(refund)
        if scoped_key is not None:
            self._refunds_by_key[scoped_key] = refund
        return refund_id

    async def cancel_subscription(
        self, stripe_subscription_id: str, *, at_period_end: bool
    ) -> None:
        self.cancelled_subscriptions.append(
            {
                "stripe_subscription_id": stripe_subscription_id,
                "at_period_end": at_period_end,
            }
        )

    async def pause_subscription_collection(
        self,
        stripe_subscription_id: str,
        *,
        behavior: str = "void",
    ) -> None:
        self.paused_subscriptions.append(
            {
                "stripe_subscription_id": stripe_subscription_id,
                "behavior": behavior,
            }
        )

    async def resume_subscription_collection(self, stripe_subscription_id: str) -> None:
        self.resumed_subscriptions.append({"stripe_subscription_id": stripe_subscription_id})

    async def update_subscription_proration(
        self,
        stripe_subscription_id: str,
        *,
        new_price_cents: int,
        billing_period_start: datetime,
        billing_period_end: datetime,
    ) -> str:
        self.subscription_prorations.append(
            {
                "stripe_subscription_id": stripe_subscription_id,
                "new_price_cents": new_price_cents,
                "billing_period_start": billing_period_start,
                "billing_period_end": billing_period_end,
            }
        )
        return ""

    def create_connect_link(self, *, redirect_uri: str, state: str) -> str:
        self.connect_links.append({"redirect_uri": redirect_uri, "state": state})
        return f"https://fake-stripe-connect.example.com/oauth?state={state}&redirect_uri={redirect_uri}"

    async def exchange_connect_code(self, code: str) -> str:
        self.connect_codes.append(code)
        return f"acct_fake_{code}"

    async def create_connected_account(
        self,
        *,
        academy_id: str,
        display_name: str | None = None,
        contact_email: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        account_id = f"acct_fake_{academy_id}_{new_ulid()}"
        self.connected_accounts.append(
            {
                "stripe_account_id": account_id,
                "academy_id": academy_id,
                "display_name": display_name,
                "contact_email": contact_email,
                "idempotency_key": idempotency_key or f"connect-account:{academy_id}",
                "dashboard": "full",
                "configuration": {
                    "merchant": {
                        "capabilities": {
                            "card_payments": {"requested": True},
                        }
                    }
                },
                "defaults": {
                    "currency": "usd",
                    "responsibilities": {
                        "fees_collector": "application",
                        "losses_collector": "application",
                    },
                },
            }
        )
        return account_id

    async def create_account_onboarding_link(
        self,
        *,
        stripe_account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> str:
        self.account_onboarding_links.append(
            {
                "stripe_account_id": stripe_account_id,
                "refresh_url": refresh_url,
                "return_url": return_url,
            }
        )
        return f"https://fake-stripe-connect.example.com/onboard/{stripe_account_id}"

    async def retrieve_connected_account(self, stripe_account_id: str) -> dict[str, Any]:
        self.retrieved_connected_accounts.append(stripe_account_id)
        return self.account_snapshots.get(
            stripe_account_id,
            {
                "id": stripe_account_id,
                "object": "account",
                "charges_enabled": False,
                "payouts_enabled": False,
                "capabilities": {},
                "requirements": {"disabled_reason": None},
            },
        )

    async def create_off_session_payment_intent(
        self,
        *,
        amount_cents: int,
        currency: str,
        customer_id: str,
        payment_method_id: str,
        idempotency_key: str,
        metadata: dict[str, str],
        connected_account_id: str | None = None,
        application_fee_cents: int = 0,
        stripe_account: str | None = None,
    ) -> tuple[str, str, str | None]:
        _check_single_route(connected_account_id, stripe_account)
        check_application_fee_cents(
            fee_cents=application_fee_cents,
            amount_cents=amount_cents,
            connected_account_id=connected_account_id or stripe_account,
        )
        # The customer and payment method must live on the account the
        # PaymentIntent is created on (Stripe: resource_missing otherwise).
        # Mirrors RealStripeGateway, which surfaces a StripeError as ValueError.
        try:
            self._require_on_account(customer_id, stripe_account, "customer")
            self._require_on_account(payment_method_id, stripe_account, "payment_method")
        except StripeResourceNotFound as exc:
            raise ValueError(f"Stripe PaymentIntent creation failed: {exc}") from exc
        pi_id = f"pi_fake_{new_ulid()}"
        self.register_object(pi_id, stripe_account=stripe_account)
        record: dict[str, Any] = {
            "id": pi_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "customer_id": customer_id,
            "payment_method_id": payment_method_id,
            "idempotency_key": idempotency_key,
            "metadata": dict(metadata),
            # Slice I: destination-charge routing (on_behalf_of +
            # transfer_data.destination) when the academy has a connected account.
            "connected_account_id": connected_account_id,
            "on_behalf_of": connected_account_id,
            "transfer_data": (
                {"destination": connected_account_id} if connected_account_id else None
            ),
            "application_fee_amount": (
                application_fee_cents if (connected_account_id or stripe_account) else None
            ),
            "stripe_account": stripe_account,
        }
        self.off_session_payment_intents.append(record)
        self._payment_intents_by_id[pi_id] = {
            "id": pi_id,
            "object": "payment_intent",
            "status": "succeeded",
            "amount": amount_cents,
            "currency": currency,
            "customer": customer_id,
            "payment_method": payment_method_id,
            "metadata": dict(metadata),
            "on_behalf_of": connected_account_id,
            "transfer_data": record["transfer_data"],
            "application_fee_amount": record["application_fee_amount"],
        }
        return pi_id, "succeeded", None

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str, stripe_account: str | None = None
    ) -> tuple[str, str] | None:
        # A Customer search only sees the Customers of the account it runs on.
        return self.saved_cards.get((stripe_account, academy_id, parent_id))


def _check_single_route(connected_account_id: str | None, stripe_account: str | None) -> None:
    if connected_account_id and stripe_account:
        raise ValueError(
            "a charge cannot be both a destination charge (connected_account_id) "
            "and a direct charge on a connected account (stripe_account)"
        )
