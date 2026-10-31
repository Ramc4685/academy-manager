"""Mongo read model behind ``GET /admin/families`` and ``/admin/families/summary``.

People CRM spec §1, §3.2 and §7 Phase 2. Builds the whole academy's family
index in a FIXED number of reads, however many families there are:

1. students of the academy and parent memberships of the academy (gathered);
2. the parent references resolved to users documents, one ``$in`` equality
   lookup per alias field (identity's ``resolve_parent_aliases``, at most
   four queries, never an ``$or`` across fields: #878/#894);
3. every child's lifecycle from the enrollment context's own batch
   derivation (the one ``/admin/students`` shows);
4. class titles and every family's money (billing's batched money read
   model, the Billing tab's balance rule), gathered.

Error handling follows the family billing read model: students, memberships,
parents and lifecycles are primary (a failure raises
:class:`FamilyIndexUnavailable`, a 503); class titles and money are secondary
(a failure leaves them empty and adds ``classes_unavailable`` /
``money_unavailable`` to ``warnings``, so the UI warns instead of showing a
zero).

Families are keyed by the parent's canonical id. A student row stored under
any alias (``user_id``, ``firebase_uid``, ``auth_uid``, users ``_id``) lands
in the same family; the per-family Billing tab resolves the same alias set,
so both views agree. Staff are excluded: a user is in the index only when a
student references them or their membership here has the ``parent`` role.

The built index is cached per academy for ``cache_ttl_seconds`` (60 s in
production, spec §3.2) so the list and the summary tiles share one build.
Every query carries ``academy_id``; ``users`` is global and is only asked
about ids read from this academy's own rows.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.v2.contexts.crm.application.family_index import FamilyIndexUnavailable
from backend.v2.contexts.crm.application.ports import (
    ChildLifecycleReader,
    FamilyMoneyFacts,
    FamilyMoneyReader,
    ParentAliasResolver,
    ResolvedParent,
)
from backend.v2.contexts.crm.domain.family_index import (
    FamilyChild,
    FamilyIndex,
    FamilyMoney,
    FamilyRecord,
    phone_digits,
)
from backend.v2.contexts.crm.domain.family_stage import roll_up_family_stage

log = logging.getLogger(__name__)

_UTC_NAME = "UTC"
#: Membership statuses that no longer make someone a family of this academy.
#: ``$nin`` rather than ``$in`` so legacy rows with no ``status`` still count.
_ENDED_MEMBERSHIP_STATUSES = ["removed", "suspended"]


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _student_name(doc: dict[str, Any]) -> str:
    full = _opt_str(doc.get("full_name"))
    if full:
        return full
    joined = " ".join(
        p for p in (_opt_str(doc.get("first_name")), _opt_str(doc.get("last_name"))) if p
    )
    return joined or "Student"


def _parent_ref(doc: dict[str, Any]) -> str | None:
    return _opt_str(doc.get("parent_id")) or _opt_str(doc.get("parent_user_id"))


def _money(facts: FamilyMoneyFacts) -> FamilyMoney:
    return FamilyMoney(
        balance_cents=facts.balance_cents,
        open_invoice_count=facts.open_invoice_count,
        overdue_invoice_count=facts.overdue_invoice_count,
        overdue_cents=facts.overdue_cents,
        oldest_overdue_due_on=facts.oldest_overdue_due_on,
        last_failed_payment_at=facts.last_failed_payment_at,
    )


class MongoFamilyIndexReadModel:
    """Batched facts → one :class:`FamilyIndex` per academy."""

    def __init__(
        self,
        db: Any,
        *,
        parents: ParentAliasResolver,
        children: ChildLifecycleReader,
        money: FamilyMoneyReader,
        academy_timezone: Callable[[str], Awaitable[str | None]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        cache_ttl_seconds: float = 0.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db = db
        self._parents = parents
        self._children = children
        self._money = money
        self._academy_timezone = academy_timezone
        self._clock = clock
        self._ttl = cache_ttl_seconds
        self._monotonic = monotonic
        self._cache: dict[str, tuple[float, FamilyIndex]] = {}

    # ------------------------------------------------------------------ entry

    async def build(self, academy_id: str) -> FamilyIndex:
        if self._ttl > 0:
            cached = self._cache.get(academy_id)
            if cached is not None and cached[0] > self._monotonic():
                return cached[1]
        index = await self._build(academy_id)
        if self._ttl > 0:
            self._cache[academy_id] = (self._monotonic() + self._ttl, index)
        return index

    async def _build(self, academy_id: str) -> FamilyIndex:
        now = self._clock()
        warnings: list[str] = []
        try:
            student_docs, member_ids = await asyncio.gather(
                self._students(academy_id), self._parent_memberships(academy_id)
            )
            raw_refs = sorted(
                {ref for doc in student_docs if (ref := _parent_ref(doc))} | set(member_ids)
            )
            resolved = await self._parents.resolve_parent_aliases(raw_refs)
            family_of: dict[str, str] = {}
            for raw in raw_refs:
                found = resolved.get(raw)
                family_of[raw] = found.canonical_id if found is not None else raw
            student_ids = [str(doc["student_id"]) for doc in student_docs if _parent_ref(doc)]
            lifecycles = await self._children.lifecycle_snapshots(
                academy_id=academy_id, student_ids=student_ids
            )
        except Exception as exc:  # primary sources
            raise FamilyIndexUnavailable(str(exc)) from exc

        # Every alias of every resolved parent points at its family, so money
        # rows stored under ANY alias are grouped with the family's children.
        family_by_alias: dict[str, str] = {}
        parent_by_family: dict[str, ResolvedParent] = {}
        for raw, family in family_of.items():
            family_by_alias.setdefault(raw, family)
            found = resolved.get(raw)
            if found is not None:
                parent_by_family.setdefault(family, found)
                for alias in sorted(found.aliases):
                    family_by_alias.setdefault(alias, family)

        session_ids = sorted({sid for snap in lifecycles.values() for sid in snap.live_session_ids})
        today = await self._today(academy_id, now)
        titles, money = await asyncio.gather(
            self._secondary(
                "classes_unavailable", warnings, self._session_titles(academy_id, session_ids), {}
            ),
            self._secondary(
                "money_unavailable",
                warnings,
                self._money.summaries(
                    academy_id=academy_id, family_by_alias=family_by_alias, today=today
                ),
                None,
            ),
        )

        children_by_family: dict[str, list[FamilyChild]] = {}
        legacy_by_family: dict[str, set[str]] = {}
        phones_by_family: dict[str, set[str]] = {}
        fallback_name: dict[str, str] = {}
        for doc in student_docs:
            ref = _parent_ref(doc)
            if ref is None:
                continue  # "Children without a family": the Students page lists them.
            family = family_of[ref]
            student_id = str(doc["student_id"])
            snap = lifecycles.get(student_id)
            live = tuple(snap.live_session_ids) if snap is not None else ()
            children_by_family.setdefault(family, []).append(
                FamilyChild(
                    student_id=student_id,
                    name=_student_name(doc),
                    lifecycle=snap.state if snap is not None else "never_enrolled",
                    lifecycle_as_of=snap.as_of if snap is not None else None,
                    session_ids=live,
                    session_titles=tuple(titles.get(sid) or sid for sid in live),
                )
            )
            roster_name = _opt_str(doc.get("parent_name")) or _opt_str(doc.get("guardian_name"))
            if roster_name:
                fallback_name.setdefault(family, roster_name)
            for key in ("parent_name", "guardian_name", "parent_email"):
                value = _opt_str(doc.get(key))
                if value:
                    legacy_by_family.setdefault(family, set()).add(value.lower())
            roster_phone = phone_digits(_opt_str(doc.get("parent_phone")))
            if roster_phone:
                phones_by_family.setdefault(family, set()).add(roster_phone)

        families: list[FamilyRecord] = []
        for family in sorted(set(family_of.values())):
            kids = sorted(
                children_by_family.get(family, []), key=lambda c: (c.name.lower(), c.student_id)
            )
            parent = parent_by_family.get(family)
            legacy = tuple(sorted(legacy_by_family.get(family, ())))
            facts = money.get(family) if money is not None else None
            families.append(
                FamilyRecord(
                    family_id=family,
                    parent_name=(parent.display_name if parent else None)
                    or fallback_name.get(family),
                    email=parent.email if parent else None,
                    phone=parent.phone if parent else None,
                    has_account=parent is not None,
                    children=tuple(kids),
                    stage=roll_up_family_stage(child.lifecycle for child in kids),
                    card_on_file=facts.card_on_file if facts is not None else None,
                    registration=facts.registration if facts is not None else None,
                    money=_money(facts) if facts is not None else None,
                    legacy_contact_keys=legacy,
                    legacy_phones=tuple(sorted(phones_by_family.get(family, ()))),
                )
            )
        families.sort(key=lambda record: record.sort_key)
        if warnings:
            log.warning("family index read model: %s for academy %s", warnings, academy_id)
        return FamilyIndex(
            academy_id=academy_id,
            generated_at=now,
            families=tuple(families),
            warnings=tuple(dict.fromkeys(warnings)),
            family_by_alias=family_by_alias,
        )

    # ------------------------------------------------------------------ helpers

    async def academy_today(self, academy_id: str) -> date:
        """The academy's calendar day now: the ``today`` every build's overdue
        split uses (People reports read it so their bands match the index)."""
        return await self._today(academy_id, self._clock())

    async def _secondary(
        self, warning: str, warnings: list[str], coro: Awaitable[Any], fallback: Any
    ) -> Any:
        try:
            return await coro
        except Exception:
            log.warning("family index read model: %s", warning, exc_info=True)
            warnings.append(warning)
            return fallback

    async def _today(self, academy_id: str, now: datetime) -> date:
        try:
            name = await self._academy_timezone(academy_id) or _UTC_NAME
            zone = ZoneInfo(name)
        except Exception:
            zone = ZoneInfo(_UTC_NAME)
        aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        return aware.astimezone(zone).date()

    # ------------------------------------------------------------------ queries
    # Every tenant query carries ``academy_id``.

    async def _students(self, academy_id: str) -> list[dict[str, Any]]:
        cursor = self._db["students"].find(
            {"academy_id": academy_id, "is_deleted": {"$ne": True}},
            {
                "_id": 0,
                "student_id": 1,
                "full_name": 1,
                "first_name": 1,
                "last_name": 1,
                "parent_id": 1,
                "parent_user_id": 1,
                "parent_name": 1,
                "guardian_name": 1,
                "parent_email": 1,
                "parent_phone": 1,
            },
        )
        return [doc async for doc in cursor if doc.get("student_id")]

    async def _parent_memberships(self, academy_id: str) -> list[str]:
        """Parents of this academy with no child on the roster yet."""
        cursor = self._db["academy_memberships"].find(
            {
                "academy_id": academy_id,
                "roles": "parent",
                "status": {"$nin": _ENDED_MEMBERSHIP_STATUSES},
            },
            {"_id": 0, "user_id": 1},
        )
        return [str(doc["user_id"]) async for doc in cursor if doc.get("user_id")]

    async def _session_titles(self, academy_id: str, session_ids: list[str]) -> dict[str, str]:
        if not session_ids:
            return {}
        cursor = self._db["sessions"].find(
            {"academy_id": academy_id, "session_id": {"$in": session_ids}},
            {"_id": 0, "session_id": 1, "title": 1, "name": 1},
        )
        return {
            str(doc["session_id"]): _opt_str(doc.get("title")) or _opt_str(doc.get("name")) or ""
            async for doc in cursor
        }
