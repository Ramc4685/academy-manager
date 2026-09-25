"""Tenant-scoped parent Stripe customer storage.

Holds payment-method / Stripe-customer data only. Autopay enrollment status
is per-enrollment (see ``student_billing_enrollments`` and
``MongoStudentBillingEnrollmentRepository``), NOT per-parent: each child's
enrollment has its own autopay on/off/paused state, so pausing one child must
not affect siblings. Only the saved payment method / Stripe customer stays
per-parent here.

Stripe account dimension (direct charges): a Stripe Customer and its saved
payment methods live on ONE Stripe account. ``stripe_account_id`` records
which: absent (the historical shape, and every house-academy row) means the
PLATFORM account; otherwise the academy's connected account the customer was
created on. The record stays one per ``(academy, parent)`` — an academy
charges on exactly one account at a time — and a write that names a
DIFFERENT account than the stored one replaces the customer and drops every
saved payment method of the old account, so a platform customer or card can
never be charged on a connected account, or the reverse.

One exception: a PLATFORM write (``stripe_account_id=None``) never replaces a
record stored on a connected account. Such a write can only be stale (e.g. a
platform checkout minted before the academy moved to direct charges,
completing afterwards); letting it through would drop the parent's connected
autopay card. It is logged and skipped. Records with no account (the house
academy) are unaffected.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from backend.v2.shared.tenancy import TenantScopedRepository

log = logging.getLogger(__name__)

#: Every field that names a saved payment method (or the setup that saved it).
#: All of them belong to the Stripe account in ``stripe_account_id``; an
#: account switch drops them together.
_PAYMENT_METHOD_FIELDS: tuple[str, ...] = (
    "default_payment_method_id",
    "payment_method_type",
    "stripe_mandate_id",
    "payment_method_label",
    "payment_method_last4",
    "autopay_setup_intent_id",
    "autopay_setup_checkout_session_id",
    "autopay_setup_completed_at",
    "autopay_payment_methods",
    *(
        f"{role}_{suffix}"
        for role in ("primary", "fallback")
        for suffix in (
            "payment_method_id",
            "payment_method_type",
            "stripe_mandate_id",
            "setup_intent_id",
            "setup_status",
            "payment_method_label",
            "payment_method_last4",
        )
    ),
)


def stored_stripe_account(doc: dict[str, Any] | None) -> str | None:
    """The Stripe account a customer record's ids live on (None = platform)."""
    if not doc:
        return None
    account = doc.get("stripe_account_id")
    return str(account) if account else None


def _platform_write_onto_connected(
    doc: dict[str, Any] | None, stripe_account_id: str | None, *, parent_id: str, op: str
) -> bool:
    """True (and logged) when a platform write targets a connected record.

    The caller must skip the write: see the module docstring.
    """
    stored = stored_stripe_account(doc)
    if stripe_account_id is None and stored is not None:
        log.warning(
            "parent_billing_customer_platform_write_skipped op=%s parent_id=%s stored_account=%s",
            op,
            parent_id,
            stored,
        )
        return True
    return False


def _account_switch_unsets(
    doc: dict[str, Any] | None, stripe_account_id: str | None, *, keep: set[str]
) -> dict[str, str]:
    """``$unset`` fields for a write onto ``stripe_account_id``.

    Empty when the stored record is on the same account (or does not exist).
    On a switch, every saved payment method of the old account is dropped
    (except ``keep``, the fields this very write sets) and, when the write
    moves to the platform, the ``stripe_account_id`` marker itself.
    """
    unset: dict[str, str] = {}
    if doc is None:
        return unset
    if stored_stripe_account(doc) != stripe_account_id:
        unset.update({field: "" for field in _PAYMENT_METHOD_FIELDS if field not in keep})
    if stripe_account_id is None and "stripe_account_id" in doc:
        unset["stripe_account_id"] = ""
    return unset


class MongoParentBillingCustomerRepository(TenantScopedRepository):
    collection_name = "parent_billing_customers"

    async def get_stripe_customer_id(self, *, parent_id: str) -> str | None:
        doc = await self._find_one({"parent_id": parent_id})
        if not doc:
            return None
        customer_id = doc.get("stripe_customer_id")
        return str(customer_id) if customer_id else None

    async def get_saved_payment_method(
        self, *, parent_id: str, stripe_account_id: str | None
    ) -> tuple[str, str] | None:
        """(stripe_customer_id, payment_method_id) of the parent's chargeable
        saved card ON ``stripe_account_id`` (None = platform), or None.

        A record stored on any other account answers None: its customer and
        payment method do not exist on ``stripe_account_id``.
        """
        doc = await self._find_one({"parent_id": parent_id})
        if not doc or stored_stripe_account(doc) != stripe_account_id:
            return None
        customer_id = doc.get("stripe_customer_id")
        if not customer_id:
            return None
        payment_method_id = doc.get("default_payment_method_id")
        if not payment_method_id and doc.get("primary_setup_status") == "active":
            payment_method_id = doc.get("primary_payment_method_id")
        if not payment_method_id:
            return None
        return str(customer_id), str(payment_method_id)

    async def set_stripe_customer_id(
        self,
        *,
        parent_id: str,
        stripe_customer_id: str,
        stripe_account_id: str | None = None,
    ) -> None:
        """Record the parent's Stripe customer on ``stripe_account_id``
        (None = platform). A customer on a different account than the stored
        one replaces it and drops the old account's saved payment methods."""
        now = datetime.now(UTC)
        doc = await self._find_one({"parent_id": parent_id})
        if _platform_write_onto_connected(
            doc, stripe_account_id, parent_id=parent_id, op="set_stripe_customer_id"
        ):
            return
        update: dict[str, object] = {
            "parent_id": parent_id,
            "stripe_customer_id": stripe_customer_id,
            "updated_at": now,
        }
        if stripe_account_id is not None:
            update["stripe_account_id"] = stripe_account_id
        mutation: dict[str, object] = {
            "$set": update,
            "$setOnInsert": {"created_at": now},
        }
        unset = _account_switch_unsets(doc, stripe_account_id, keep=set())
        if unset:
            mutation["$unset"] = unset
        await self._update_one({"parent_id": parent_id}, mutation, upsert=True)

    async def set_default_payment_method(
        self,
        *,
        parent_id: str,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        payment_method_type: str,
        stripe_mandate_id: str | None,
        setup_intent_id: str,
        checkout_session_id: str | None,
        completed_at: datetime,
        current_consent_id: str | None = None,
        consent_text_version: str | None = None,
        ach_mandate_version: str | None = None,
        card_disclosure_version: str | None = None,
        setup_status: str = "active",
        payment_method_role: str = "primary",
        payment_method_label: str | None = None,
        payment_method_last4: str | None = None,
        session: Any | None = None,
        stripe_account_id: str | None = None,
    ) -> None:
        """``stripe_account_id`` is the account the customer and payment
        method live on (None = platform). A platform write onto a record
        stored on a connected account is skipped (see the module docstring)."""
        existing = await self._find_one({"parent_id": parent_id}, session=session)
        if _platform_write_onto_connected(
            existing, stripe_account_id, parent_id=parent_id, op="set_default_payment_method"
        ):
            return
        now = datetime.now(UTC)
        role = payment_method_role if payment_method_role in {"primary", "fallback"} else "primary"
        method_projection: dict[str, object] = {
            "role": role,
            "stripe_payment_method_id": stripe_payment_method_id,
            "payment_method_type": payment_method_type,
            "setup_intent_id": setup_intent_id,
            "setup_status": setup_status,
            "updated_at": completed_at,
        }
        if stripe_mandate_id:
            method_projection["stripe_mandate_id"] = stripe_mandate_id
        if payment_method_label:
            method_projection["payment_method_label"] = payment_method_label
        if payment_method_last4:
            method_projection["payment_method_last4"] = payment_method_last4
        if checkout_session_id:
            method_projection["checkout_session_id"] = checkout_session_id
        unset: dict[str, str] = {}
        update: dict[str, object] = {
            "parent_id": parent_id,
            "stripe_customer_id": stripe_customer_id,
            "autopay_setup_intent_id": setup_intent_id,
            "autopay_setup_completed_at": completed_at,
            "updated_at": now,
            f"{role}_payment_method_id": stripe_payment_method_id,
            f"{role}_payment_method_type": payment_method_type,
            f"{role}_setup_intent_id": setup_intent_id,
            f"{role}_setup_status": setup_status,
        }
        if payment_method_label:
            update[f"{role}_payment_method_label"] = payment_method_label
        else:
            unset[f"{role}_payment_method_label"] = ""
        if payment_method_last4:
            update[f"{role}_payment_method_last4"] = payment_method_last4
        else:
            unset[f"{role}_payment_method_last4"] = ""
        if current_consent_id:
            update["current_autopay_consent_id"] = current_consent_id
        if consent_text_version:
            update["current_consent_text_version"] = consent_text_version
        if ach_mandate_version:
            update["current_ach_mandate_version"] = ach_mandate_version
            update.pop("current_card_disclosure_version", None)
        if card_disclosure_version:
            update["current_card_disclosure_version"] = card_disclosure_version
            update.pop("current_ach_mandate_version", None)
        if role == "primary":
            update["primary_payment_method_id"] = stripe_payment_method_id
            update["primary_payment_method_type"] = payment_method_type
            update["primary_setup_status"] = setup_status
            if payment_method_label:
                update["primary_payment_method_label"] = payment_method_label
            if payment_method_last4:
                update["primary_payment_method_last4"] = payment_method_last4
            if setup_status == "active":
                if payment_method_label:
                    update["payment_method_label"] = payment_method_label
                else:
                    unset["payment_method_label"] = ""
                if payment_method_last4:
                    update["payment_method_last4"] = payment_method_last4
                else:
                    unset["payment_method_last4"] = ""
        if stripe_mandate_id:
            update[f"{role}_stripe_mandate_id"] = stripe_mandate_id
        if checkout_session_id:
            update["autopay_setup_checkout_session_id"] = checkout_session_id
        if ach_mandate_version:
            unset["current_card_disclosure_version"] = ""
        if card_disclosure_version:
            unset["current_ach_mandate_version"] = ""
        if stripe_account_id is not None:
            update["stripe_account_id"] = stripe_account_id
        for field in _account_switch_unsets(existing, stripe_account_id, keep=set(update)):
            unset.setdefault(field, "")
        mutation: dict[str, object] = {
            "$set": update,
            "$setOnInsert": {"created_at": now},
        }
        if unset:
            mutation["$unset"] = unset
        await self._update_one(
            {"parent_id": parent_id},
            mutation,
            upsert=True,
            session=session,
        )
        await self._update_one(
            {"parent_id": parent_id},
            {"$pull": {"autopay_payment_methods": {"role": role}}},
            upsert=False,
            session=session,
        )
        await self._update_one(
            {"parent_id": parent_id},
            {"$push": {"autopay_payment_methods": method_projection}},
            upsert=False,
            session=session,
        )

    async def promote_payment_method_to_default(
        self,
        *,
        parent_id: str,
        stripe_payment_method_id: str,
        payment_method_type: str,
        stripe_mandate_id: str | None,
        payment_method_label: str | None = None,
        payment_method_last4: str | None = None,
        stripe_account_id: str | None = None,
    ) -> None:
        """Only promotes on the record stored for ``stripe_account_id``
        (None = platform): a payment method never becomes the default of a
        customer on another account."""
        update: dict[str, object] = {
            "default_payment_method_id": stripe_payment_method_id,
            "payment_method_type": payment_method_type,
            "updated_at": datetime.now(UTC),
        }
        if stripe_mandate_id:
            update["stripe_mandate_id"] = stripe_mandate_id
        unset: dict[str, str] = {}
        if payment_method_label:
            update["payment_method_label"] = payment_method_label
        else:
            unset["payment_method_label"] = ""
        if payment_method_last4:
            update["payment_method_last4"] = payment_method_last4
        else:
            unset["payment_method_last4"] = ""
        mutation: dict[str, object] = {"$set": update}
        if unset:
            mutation["$unset"] = unset
        # ``None`` matches both a missing field (every historical platform
        # row) and an explicit null.
        await self._update_one(
            {"parent_id": parent_id, "stripe_account_id": stripe_account_id},
            mutation,
            upsert=False,
        )

    async def list_academy_customers(self) -> list[dict[str, Any]]:
        """One row per parent with a billing-customer record in this academy.

        Projects only display-safe fields for the Billing Setup admin page —
        ``payment_method_label``/``payment_method_last4`` are set only when
        the primary payment method's setup is ``active`` (see
        ``set_default_payment_method``), so their presence here is exactly
        the "has a chargeable saved card" signal.
        """
        projection = {
            "parent_id": 1,
            "stripe_customer_id": 1,
            "payment_method_label": 1,
            "payment_method_last4": 1,
            "primary_payment_method_label": 1,
            "primary_payment_method_last4": 1,
            "primary_setup_status": 1,
            "autopay_payment_methods": 1,
            "billing_setup_last_invited_at": 1,
        }
        cursor = self.collection.find(self._scoped({}), projection)
        return [doc async for doc in cursor]

    async def get_academy_customer(self, *, parent_id: str) -> dict[str, Any] | None:
        return await self._find_one({"parent_id": parent_id})

    async def has_saved_card(self, *, parent_id: str) -> bool:
        """Whether this parent has a chargeable primary payment method —
        the same "card on file" signal ``list_academy_customers`` projects,
        for single-parent guard checks (charge / enable-autopay endpoints)."""
        doc = await self._find_one({"parent_id": parent_id})
        if not doc:
            return False
        return self.display_payment_method(doc) != (None, None)

    @staticmethod
    def display_payment_method(doc: dict[str, Any]) -> tuple[str | None, str | None]:
        """Resolve safe display fields across current and compatibility shapes."""
        label = doc.get("payment_method_label")
        last4 = doc.get("payment_method_last4")
        if label or last4:
            return (str(label) if label else None, str(last4) if last4 else None)
        if doc.get("primary_setup_status") == "active":
            primary_label = doc.get("primary_payment_method_label")
            primary_last4 = doc.get("primary_payment_method_last4")
            if primary_label or primary_last4:
                return (
                    str(primary_label) if primary_label else None,
                    str(primary_last4) if primary_last4 else None,
                )
        for method in doc.get("autopay_payment_methods") or []:
            if method.get("role") == "primary" and method.get("setup_status") == "active":
                nested_label = method.get("payment_method_label")
                nested_last4 = method.get("payment_method_last4")
                if nested_label or nested_last4:
                    return (
                        str(nested_label) if nested_label else None,
                        str(nested_last4) if nested_last4 else None,
                    )
        return None, None

    async def record_billing_setup_invite(self, *, parent_id: str, sent_at: datetime) -> None:
        """Track when the Billing Setup admin page last invited this parent
        (login invite or add-card reminder), so the UI can show "Invited
        {date}" and offer a resend."""
        await self._update_one(
            {"parent_id": parent_id},
            {
                "$set": {"billing_setup_last_invited_at": sent_at},
                "$setOnInsert": {"created_at": sent_at, "parent_id": parent_id},
            },
            upsert=True,
        )
