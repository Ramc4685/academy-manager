"""Composition for the People CRM family index (``/admin/families``, ``/summary``).

People CRM spec §1 and §7 Phase 2: wiring only, zero lines in
``composition/admin.py`` (at its line budget). The CRM context may not import
identity, enrollment or billing, so this module hands it each owner's
implementation of the CRM ports:

* identity's ``MongoUserRepository.resolve_parent_aliases`` (parent aliases,
  one equality lookup per field);
* enrollment's ``MongoStudentRepository.lifecycle_snapshots`` (the
  ``/admin/students`` lifecycle derivation, batched);
* billing's ``MongoFamilyMoneyReadModel`` (every family's money, the Billing
  tab's balance rule).

It also wires the People reports on ``/admin/reports`` (roadmap L5a): money
owed by age band reads the SAME index instance (so it shares the index's
cache and alias map) and the same billing money read model; inquiry
conversion reads ``crm_contacts`` through the tenant-scoped repository.
Attached as ``AdminFamilyIndex.reports`` so ``main.py`` needs no new line.
The L5b cards ride on the same bundle: attendance risk reads enrollment's
``lifecycle_snapshots`` (the same derivation the index uses) and names each
class's coach with the admin sessions list's membership-gated lookup;
families lost reads the SAME index instance and ``enrollment_events``.

Nothing tenant-specific is captured: every read takes the request's
``academy_id``.

Phase 4a (family notes and follow-ups, migration 0195) rides on the same
``app.state.admin_family_index`` bundle: the notes and follow-ups use cases
need the index to prove a family belongs to the academy, and hanging them
here keeps ``main.py`` and ``composition/admin.py`` untouched. The follow-up
assignee check is identity's membership lookup, handed in as a closure that
takes the academy at call time.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from backend.v2.composition.admin_session_staff import attach_session_staff_names
from backend.v2.contexts.billing.infrastructure.family_money_read_model import (
    MongoFamilyMoneyReadModel,
)
from backend.v2.contexts.crm.application.family_directory import IndexFamilyDirectory
from backend.v2.contexts.crm.application.people_reports import (
    AttendanceRiskReport,
    FamiliesLostReport,
    InquiryConversionReport,
    MoneyOwedByAgeReport,
)
from backend.v2.contexts.crm.application.use_cases.family_follow_ups import (
    AddFamilyFollowUp,
    ListFamilyFollowUps,
    ListFollowUps,
    UpdateFamilyFollowUp,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import (
    AddFamilyNote,
    DeleteFamilyNote,
    EditFamilyNote,
    ListFamilyNotes,
)
from backend.v2.contexts.crm.infrastructure.family_index_read_model import (
    MongoFamilyIndexReadModel,
)
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_notes_repo import (
    MongoFamilyFollowUpRepository,
    MongoFamilyNoteRepository,
)
from backend.v2.contexts.crm.infrastructure.people_reports_read_model import (
    MongoAttendanceRiskSource,
    MongoDepartureSource,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
    MongoMembershipRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

#: Spec §3.2: the index is rebuilt at most once a minute per academy, so the
#: list and the summary tiles of one page load share a build.
FAMILY_INDEX_CACHE_TTL_SECONDS = 60.0


#: Academy roles that may be assigned a follow-up (the CRM is admin-only).
FOLLOW_UP_ASSIGNEE_ROLES = frozenset({"admin", "owner"})


@dataclass(frozen=True)
class AdminFamilyNotes:
    list: ListFamilyNotes
    add: AddFamilyNote
    edit: EditFamilyNote
    delete: DeleteFamilyNote


@dataclass(frozen=True)
class AdminFamilyFollowUps:
    list: ListFamilyFollowUps
    add: AddFamilyFollowUp
    update: UpdateFamilyFollowUp
    queue: ListFollowUps


@dataclass(frozen=True)
class AdminPeopleReports:
    money_owed_by_age: MoneyOwedByAgeReport
    inquiry_conversion: InquiryConversionReport
    attendance_risk: AttendanceRiskReport
    families_lost: FamiliesLostReport


@dataclass(frozen=True)
class AdminFamilyIndex:
    index: MongoFamilyIndexReadModel
    reports: AdminPeopleReports
    notes: AdminFamilyNotes | None = None
    follow_ups: AdminFamilyFollowUps | None = None


class _MembershipStaffDirectory:
    """Identity's membership row, read with the user's aliases: active, with an
    admin or owner role in THIS academy."""

    def __init__(self, db: Any) -> None:
        self._users = MongoUserRepository(db)
        self._memberships = MongoMembershipRepository(db)

    async def is_staff(self, academy_id: str, user_id: str) -> bool:
        resolved = (await self._users.resolve_parent_aliases([user_id])).get(user_id)
        aliases = sorted(resolved.aliases) if resolved is not None else None
        membership = await self._memberships.get_membership(academy_id, user_id, aliases=aliases)
        if membership is None or not membership.is_active():
            return False
        return any(role in FOLLOW_UP_ASSIGNEE_ROLES for role in membership.roles)


def _coach_names(db: Any) -> Callable[[str, Sequence[str]], Awaitable[Mapping[str, str]]]:
    """Coach display names the way the admin sessions list resolves them:
    only ids with a membership in ``academy_id`` get a name."""

    async def names(academy_id: str, coach_ids: Sequence[str]) -> Mapping[str, str]:
        rows: list[dict[str, Any]] = [{"coach_id": cid} for cid in coach_ids]
        with tenant_scope(academy_id):
            await attach_session_staff_names(db, rows)
        return {
            str(row["coach_id"]): str(row["coach_name"]) for row in rows if row.get("coach_name")
        }

    return names


def _index_model(
    db: Any, cache_ttl_seconds: float, money: MongoFamilyMoneyReadModel | None = None
) -> MongoFamilyIndexReadModel:
    return MongoFamilyIndexReadModel(
        db,
        parents=MongoUserRepository(db),
        children=MongoStudentRepository(db),
        money=money if money is not None else MongoFamilyMoneyReadModel(db),
        academy_timezone=academy_timezone_lookup(db),
        cache_ttl_seconds=cache_ttl_seconds,
    )


def compose_admin_family_index(db: Any) -> AdminFamilyIndex:
    money = MongoFamilyMoneyReadModel(db)
    index = _index_model(db, FAMILY_INDEX_CACHE_TTL_SECONDS, money)
    families = IndexFamilyDirectory(cached=index, fresh=_index_model(db, 0.0))
    notes = MongoFamilyNoteRepository(db)
    follow_ups = MongoFamilyFollowUpRepository(db)
    staff = _MembershipStaffDirectory(db)
    timezone = academy_timezone_lookup(db)
    return AdminFamilyIndex(
        index=index,
        reports=AdminPeopleReports(
            money_owed_by_age=MoneyOwedByAgeReport(index=index, money=money),
            inquiry_conversion=InquiryConversionReport(
                contacts=MongoCrmContactRepository(db), academy_timezone=timezone
            ),
            attendance_risk=AttendanceRiskReport(
                source=MongoAttendanceRiskSource(
                    db, children=MongoStudentRepository(db), coach_names=_coach_names(db)
                )
            ),
            families_lost=FamiliesLostReport(
                index=index, departures=MongoDepartureSource(db), academy_timezone=timezone
            ),
        ),
        notes=AdminFamilyNotes(
            list=ListFamilyNotes(notes, families),
            add=AddFamilyNote(notes, families),
            edit=EditFamilyNote(notes, families),
            delete=DeleteFamilyNote(notes, families),
        ),
        follow_ups=AdminFamilyFollowUps(
            list=ListFamilyFollowUps(follow_ups, families, staff, timezone),
            add=AddFamilyFollowUp(follow_ups, families, staff, timezone),
            update=UpdateFamilyFollowUp(follow_ups, families, staff, timezone),
            queue=ListFollowUps(follow_ups, families, staff, timezone),
        ),
    )
