"""Mongo-backed audience resolver.

Resolves audience descriptors to concrete recipient lists by querying
the users, enrollments, and students collections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    CoachAudience,
    PaymentRiskAudience,
    SelectedRecipientsAudience,
    SessionAudience,
)
from backend.v2.shared.tenancy.context import current_academy_id

#: Enrollment statuses whose family hears about a session: the roster's own
#: definition of "in this class" (``ROSTER_VISIBLE`` in
#: contexts/enrollment/domain/models.py — "active" and "held" today). A held
#: student keeps their seat and still shows on the roster, so their parent
#: gets the class's messages; a paused or ended enrollment does not.
#: Communications cannot import contexts.enrollment (Rule 5, no cross-context
#: imports, tests/structural/test_layering.py), so the set is mirrored here
#: and pinned to ROSTER_VISIBLE by
#: tests/infrastructure/test_mongo_audience_resolver.py.
SESSION_AUDIENCE_ENROLLMENT_STATUSES: frozenset[str] = frozenset({"active", "held"})

#: People CRM Phase 4b (migration 0196): a family contact (second parent,
#: guardian, ...) who has "Gets notices" switched on receives the family's
#: notices. Contacts are never users, so each gets a synthetic, stable
#: recipient id under this prefix (the unsubscribe link and the preference
#: gate key on it like any other recipient id). The collection is written by
#: the CRM context; communications may not import it (Rule 5), so it is read
#: here by name, like ``students`` and ``enrollments`` above.
FAMILY_CONTACTS_COLLECTION = "family_contacts"
FAMILY_CONTACT_RECIPIENT_PREFIX = "family_contact:"


@dataclass
class MongoAudienceResolver(AudienceResolver):
    db: AsyncIOMotorDatabase

    def _role_filter(self, role: str) -> dict[str, Any]:
        return {
            "academy_id": current_academy_id(),
            "$or": [{"role": role}, {"roles": role}],
        }

    def _membership_role_filter(self, role: str) -> dict[str, Any]:
        return {
            "academy_id": current_academy_id(),
            "status": "active",
            "$or": [{"role": role}, {"roles": role}],
        }

    async def _resolve_users_for_ids(self, user_ids: list[str]) -> list[ResolvedRecipient]:
        """Fetch user docs for ids, scoped to the current academy.

        The users collection holds one doc per (user, academy) for
        multi-academy users, plus legacy global docs without academy_id.
        Match the current tenant's doc or a global doc — never another
        academy's — and dedupe by user_id, preferring the tenant-scoped
        doc so its email/display name wins over a global fallback.
        """
        academy_id = current_academy_id()
        cursor = self.db["users"].find(
            {
                "academy_id": {"$in": [academy_id, None]},
                "$or": [{"user_id": {"$in": user_ids}}, {"auth_uid": {"$in": user_ids}}],
            },
            {"user_id": 1, "academy_id": 1, "email": 1, "display_name": 1, "name": 1},
        )
        best: dict[str, dict[str, Any]] = {}
        async for doc in cursor:
            key = str(doc.get("user_id") or doc.get("_id"))
            existing = best.get(key)
            if existing is None or (
                existing.get("academy_id") != academy_id and doc.get("academy_id") == academy_id
            ):
                best[key] = doc
        return [self._user_to_recipient(doc) for doc in best.values()]

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        membership_cursor = self.db["academy_memberships"].find(
            self._membership_role_filter(audience.role),
            {"user_id": 1},
        )
        user_ids = [str(doc["user_id"]) async for doc in membership_cursor if doc.get("user_id")]
        if user_ids:
            return await self._resolve_users_for_ids(user_ids)

        legacy_cursor = self.db["users"].find(
            self._role_filter(audience.role),
            {"user_id": 1, "email": 1, "display_name": 1, "name": 1},
        )
        return [self._user_to_recipient(doc) async for doc in legacy_cursor]

    async def resolve_session_audience(self, audience: SessionAudience) -> list[ResolvedRecipient]:
        academy_id = current_academy_id()
        enrollment_cursor = self.db["enrollments"].find(
            {
                "academy_id": academy_id,
                "session_id": audience.session_id,
                "status": {"$in": sorted(SESSION_AUDIENCE_ENROLLMENT_STATUSES)},
            },
            {"student_id": 1},
        )
        student_ids = [str(doc["student_id"]) async for doc in enrollment_cursor]
        if not student_ids:
            return []

        student_cursor = self.db["students"].find(
            {"academy_id": academy_id, "student_id": {"$in": student_ids}},
            {"parent_id": 1, "parent_user_id": 1},
        )
        parent_ids: set[str] = set()
        async for doc in student_cursor:
            pid = doc.get("parent_id") or doc.get("parent_user_id")
            if pid:
                parent_ids.add(str(pid))

        if not parent_ids:
            return []

        # A student's parent id may be the parent's user_id or their Firebase
        # auth_uid alias; resolve both, deduped, current tenant (or legacy
        # global doc) only — the same lookup every other parent audience uses.
        parents = await self._resolve_users_for_ids(sorted(parent_ids))
        return await self._with_family_contacts(parents, parent_ids)

    async def resolve_coach_audience(self, audience: CoachAudience) -> list[ResolvedRecipient]:
        if audience.session_id:
            academy_id = current_academy_id()
            session_doc = await self.db["sessions"].find_one(
                {"academy_id": academy_id, "session_id": audience.session_id},
                {"coach_id": 1},
            )
            if not session_doc or not session_doc.get("coach_id"):
                return []
            coach_id = str(session_doc["coach_id"])
            user_doc = await self.db["users"].find_one(
                {
                    "academy_id": academy_id,
                    "$or": [{"user_id": coach_id}, {"auth_uid": coach_id}],
                },
                {"user_id": 1, "email": 1, "display_name": 1, "name": 1},
            )
            if not user_doc:
                return []
            return [self._user_to_recipient(user_doc)]
        return await self.resolve_academy_audience(AcademyAudience(role="coach"))

    async def resolve_selected_audience(
        self, audience: SelectedRecipientsAudience
    ) -> list[ResolvedRecipient]:
        academy_id = current_academy_id()
        cursor = self.db["users"].find(
            {"academy_id": academy_id, "user_id": {"$in": list(audience.user_ids)}},
            {"user_id": 1, "email": 1, "display_name": 1, "name": 1},
        )
        users = [self._user_to_recipient(doc) async for doc in cursor]
        if not audience.include_family_contacts:
            return users
        # Contacts are appended AFTER the users, so a caller that reads the
        # selected parent as ``resolved[0]`` still gets the parent.
        return await self._with_family_contacts(users, set())

    async def resolve_payment_risk_audience(
        self, audience: PaymentRiskAudience
    ) -> list[ResolvedRecipient]:
        from datetime import UTC, datetime, timedelta

        academy_id = current_academy_id()
        cutoff = datetime.now(UTC) - timedelta(days=audience.min_days_overdue)
        invoice_cursor = self.db["invoices"].find(
            {
                "academy_id": academy_id,
                # Only payable statuses: draft invoices are excluded because the
                # parent checkout/digest paths treat only open/partially_paid as
                # payable — emailing about a draft balance would 404 the pay flow.
                "status": {"$in": ["open", "partially_paid"]},
                "balance_due_cents": {"$gt": 0},
                "due_date": {"$lt": cutoff},
                "is_deleted": {"$ne": True},
            },
            {"parent_id": 1, "parent_user_id": 1},
        )
        user_ids = list(
            {
                str(doc.get("parent_id") or doc.get("parent_user_id"))
                async for doc in invoice_cursor
                if doc.get("parent_id") or doc.get("parent_user_id")
            }
        )
        if not user_ids:
            cursor = self.db["payments"].find(
                {"academy_id": academy_id, "status": "pending", "due_date": {"$lt": cutoff}},
                {"user_id": 1},
            )
            user_ids = list({str(doc["user_id"]) async for doc in cursor if doc.get("user_id")})
        if not user_ids:
            return []
        # Every id here came from this academy's overdue invoices/payments, so
        # the set is already tenant-scoped. Resolve them all: narrowing to
        # active parent memberships would silently drop delinquent parents who
        # have a tenant-scoped (or legacy global) user doc but no active
        # academy_memberships doc — the issue asked for de-duplication and
        # academy scoping, not for excluding membership-less tenant users.
        # _resolve_users_for_ids keeps the cross-tenant fix: it only matches
        # the current academy's doc or a global doc, never another tenant's.
        return await self._resolve_users_for_ids(user_ids)

    async def _with_family_contacts(
        self, parents: list[ResolvedRecipient], raw_parent_ids: set[str]
    ) -> list[ResolvedRecipient]:
        """``parents`` plus every opted-in family contact of those families.

        The per-parent expansion (People CRM spec §4 "Second parent"): a
        contact is added only when ``gets_notices`` is true, only from the
        current academy's ``family_contacts`` rows (the filter carries
        ``academy_id``), and only once per lowercased email — never a second
        copy of an address already in the list, the primary parent's
        included. Contacts are keyed by the family's canonical parent id, the
        user's ``user_id``; the raw ids (a student's ``parent_id`` may be an
        ``auth_uid`` alias) are matched too. One ``$in`` on one field, served
        by the ``(academy_id, parent_id, created_at)`` index.

        Bounced or complained addresses are not filtered here: every send goes
        through ``GatedEmailSendPort``, whose suppression gate checks the email
        itself, so a suppressed contact is refused at send time exactly as a
        suppressed parent is.
        """
        family_ids = {r.user_id for r in parents if r.user_id} | set(raw_parent_ids)
        if not family_ids:
            return parents
        cursor = (
            self.db[FAMILY_CONTACTS_COLLECTION]
            .find(
                {
                    "academy_id": current_academy_id(),
                    "parent_id": {"$in": sorted(family_ids)},
                    "gets_notices": True,
                },
                {"contact_id": 1, "email": 1, "name": 1},
            )
            .sort([("parent_id", 1), ("created_at", 1)])
        )
        seen = {r.email.strip().lower() for r in parents if r.email and r.email.strip()}
        recipients = list(parents)
        async for doc in cursor:
            email = str(doc.get("email") or "").strip().lower()
            contact_id = doc.get("contact_id")
            if not email or not contact_id or email in seen:
                continue
            seen.add(email)
            recipients.append(
                ResolvedRecipient(
                    user_id=f"{FAMILY_CONTACT_RECIPIENT_PREFIX}{contact_id}",
                    email=email,
                    display_name=doc.get("name"),
                )
            )
        return recipients

    @staticmethod
    def _user_to_recipient(doc: dict[str, Any]) -> ResolvedRecipient:
        return ResolvedRecipient(
            user_id=str(doc.get("user_id") or doc.get("_id")),
            email=doc.get("email"),
            display_name=doc.get("display_name") or doc.get("name"),
        )
