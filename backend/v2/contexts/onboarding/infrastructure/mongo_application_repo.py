"""Mongo ApplicationRepository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.v2.contexts.onboarding.domain.models import (
    Application,
    ChildProfile,
    ParentProfile,
    WaiverAcceptance,
)
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoApplicationRepository(TenantScopedRepository):
    collection_name = "onboarding_applications"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Application:
        wa = doc.get("waiver_acceptance")
        superseded = doc.get("superseded_payment_ids")
        return Application(
            application_id=str(doc["application_id"]),
            academy_id=str(doc["academy_id"]),
            parent_user_id=str(doc["parent_user_id"]),
            parent_email=str(doc["parent_email"]),
            status=doc.get("status", "DRAFT"),
            parent_profile=ParentProfile.model_validate(doc.get("parent_profile") or {}),
            child_profile=ChildProfile.model_validate(doc.get("child_profile") or {}),
            selected_session_id=doc.get("selected_session_id"),
            waiver_acceptance=WaiverAcceptance.model_validate(wa) if wa else None,
            stripe_checkout_session_id=doc.get("stripe_checkout_session_id"),
            payment_id=doc.get("payment_id"),
            superseded_payment_ids=(
                [str(pid) for pid in superseded] if isinstance(superseded, list) else []
            ),
            student_id=doc.get("student_id"),
            enrollment_id=doc.get("enrollment_id"),
            waitlist_id=doc.get("waitlist_id"),
            decision_reason=doc.get("decision_reason"),
            decided_by=doc.get("decided_by"),
            decided_at=doc.get("decided_at"),
            review_claimed_at=doc.get("review_claimed_at"),
            review_claim_token=doc.get("review_claim_token"),
            zero_quote_period=doc.get("zero_quote_period"),
            expires_at=doc["expires_at"],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    async def save(self, app: Application) -> None:
        doc = app.model_dump(mode="python")
        await self._update_one(
            {"application_id": app.application_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def get(self, application_id: str) -> Application | None:
        doc = await self._find_one({"application_id": application_id})
        return self._to_domain(doc) if doc else None

    async def latest_for_parent(self, parent_user_id: str) -> Application | None:
        cursor = self._find_many(
            {"parent_user_id": parent_user_id},
            sort=[("created_at", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_domain(doc)
        return None

    async def get_by_payment_id(self, payment_id: str) -> Application | None:
        """Resolve an application from a payment id — current OR superseded.

        A re-stamp re-points `payment_id` at the newest checkout attempt, and
        the parent may have completed the attempt it replaced moments earlier
        (charge accepted, webhook not yet landed). This lookup is the only
        handle `checkout.session.completed` has back to the application, so
        matching the archived ids too is what stops that charge orphaning the
        registration (#549). Payment ids are unique per attempt, so the $or can
        never match two different applications.
        """
        doc = await self._find_one(
            {
                "$or": [
                    {"payment_id": payment_id},
                    {"superseded_payment_ids": payment_id},
                ]
            }
        )
        return self._to_domain(doc) if doc else None

    async def list_by_status(self, statuses: list[str]) -> list[Application]:
        cursor = self._find_many(
            {"status": {"$in": statuses}},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def reopen_for_edit(
        self, application_id: str, *, expected_status: str, updated_at: datetime
    ) -> Application | None:
        """Atomically return an abandoned checkout attempt to DRAFT.

        Compare-and-set on the status the caller read. A read-then-write here
        would resurrect an application the payment webhook had ALREADY moved
        to PENDING_APPROVAL in the parent's other tab — unpicking a real
        charge. Returns None when the application moved on; the caller must
        never treat that as a reason to write anyway.
        """
        doc = await self._find_one_and_update(
            {"application_id": application_id, "status": expected_status},
            {"$set": {"status": "DRAFT", "updated_at": updated_at}},
        )
        return self._to_domain(doc) if doc else None

    async def restamp_checkout(
        self,
        application_id: str,
        *,
        expected_status: str,
        expected_payment_id: str | None,
        stripe_checkout_session_id: str | None,
        payment_id: str | None,
        updated_at: datetime,
        new_status: str | None = None,
    ) -> Application | None:
        """Atomically point an application at a live checkout.

        CAS covers `payment_id` as well as `status` so two concurrent
        `POST /parent/checkout/start` calls cannot both believe they own the
        application — the loser misses and leaves the winner's payment in
        place. ``expected_payment_id=None`` matches a document with no payment
        stamped yet (missing or null).

        ``new_status`` moves the status as part of the same atomic write, for
        the DRAFT -> CHECKOUT_PENDING claim. Omit it to re-point an
        application that is already CHECKOUT_PENDING, where the status must
        not move. Both callers need the same CAS: the entry transition is
        where two tabs first race, and a blind write there mints a second
        payable Stripe session just as surely as a blind re-stamp does.
        """
        filter_: dict[str, Any] = {
            "application_id": application_id,
            "status": expected_status,
            "payment_id": expected_payment_id,
        }
        updates: dict[str, Any] = {"updated_at": updated_at}
        if new_status is not None:
            updates["status"] = new_status
        if stripe_checkout_session_id is not None:
            updates["stripe_checkout_session_id"] = stripe_checkout_session_id
        if payment_id is not None:
            updates["payment_id"] = payment_id
        update: dict[str, Any] = {"$set": updates}
        if (
            expected_payment_id is not None
            and payment_id is not None
            and payment_id != expected_payment_id
        ):
            # Archive the id we are overwriting, in the SAME atomic write as
            # the overwrite. A separate follow-up write could be lost to a
            # crash, and the window it opens is exactly the dangerous one: the
            # parent has already paid the superseded session and the webhook
            # lands with nothing pointing back at the application (#549).
            update["$addToSet"] = {"superseded_payment_ids": expected_payment_id}
        doc = await self._find_one_and_update(filter_, update)
        return self._to_domain(doc) if doc else None

    async def claim_for_review(
        self,
        application_id: str,
        processing_status: str,
        *,
        claim_token: str,
        updated_at: datetime,
        stale_before: datetime,
    ) -> Application | None:
        """Atomically grant one admin decision worker ownership of an application."""
        doc = await self._find_one_and_update(
            {
                "application_id": application_id,
                "$or": [
                    {"status": "PENDING_APPROVAL"},
                    {
                        "status": processing_status,
                        "$or": [
                            {"review_claimed_at": {"$lte": stale_before}},
                            {"review_claimed_at": {"$exists": False}},
                            {"review_claimed_at": None},
                        ],
                    },
                ],
            },
            {
                "$set": {
                    "status": processing_status,
                    "review_claimed_at": updated_at,
                    "review_claim_token": claim_token,
                    "updated_at": updated_at,
                }
            },
        )
        return self._to_domain(doc) if doc else None

    async def release_review(
        self,
        application_id: str,
        processing_status: str,
        *,
        claim_token: str,
        updated_at: datetime,
    ) -> None:
        await self._update_one(
            {
                "application_id": application_id,
                "status": processing_status,
                "review_claim_token": claim_token,
            },
            {
                "$set": {"status": "PENDING_APPROVAL", "updated_at": updated_at},
                "$unset": {"review_claimed_at": "", "review_claim_token": ""},
            },
        )

    async def renew_review_claim(
        self, application_id: str, claim_token: str, *, claimed_at: datetime
    ) -> bool:
        result = await self._update_one(
            {
                "application_id": application_id,
                "status": {"$in": ["APPROVING", "WAITLISTING", "DECLINING"]},
                "review_claim_token": claim_token,
            },
            {"$set": {"review_claimed_at": claimed_at, "updated_at": claimed_at}},
        )
        return result.matched_count == 1

    async def complete_review(self, app: Application, *, claim_token: str) -> bool:
        doc = app.model_dump(mode="python")
        values = {
            key: value
            for key, value in doc.items()
            if key not in {"academy_id", "review_claim_token", "review_claimed_at"}
        }
        result = await self._update_one(
            {"application_id": app.application_id, "review_claim_token": claim_token},
            {
                "$set": values,
                "$unset": {"review_claim_token": "", "review_claimed_at": ""},
            },
        )
        return result.matched_count == 1
