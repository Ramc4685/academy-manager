"""Admin BFF: People reports on ``/admin/reports`` (roadmap item L5a).

Two read-only routes, both ``require_persona("admin")`` like every People CRM
route (a non-admin persona gets 404, never 403):

* ``GET /admin/reports/people/money-owed-by-age``: open balance by days past
  due, family count and total per band. Money: the caller must also pass
  ``can_view_family_money`` (the #553 staff-tier seam), otherwise **403**
  (the caller is already inside an authorized admin route, so nothing is
  leaked and the UI hides the card on that status).
* ``GET /admin/reports/people/inquiry-conversion?from=&to=``: ``crm_contacts``
  by source and pipeline status over academy-local days (default: the last
  90). No money.
* ``GET /admin/reports/people/attendance-risk`` (L5b): students whose
  lifecycle is at_risk, by class and by the class's coach. No money.
* ``GET /admin/reports/people/families-lost?from=&to=`` (L5b): families that
  left in the window, by recorded reason, else by how they left. No money.

Services come from ``app.state.admin_family_index.reports``
(``composition/families_crm.py``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.v2.contexts.crm.application.family_index import FamilyIndexUnavailable
from backend.v2.contexts.crm.application.money_visibility import can_view_family_money
from backend.v2.contexts.crm.application.people_reports import (
    AgeBandTotal,
    AttendanceRisk,
    ClassRiskRow,
    CoachRiskRow,
    FamiliesLost,
    InquiryConversion,
    InvalidReportRange,
    MoneyOwedByAge,
    PeopleReportUnavailable,
    ReasonCount,
    SourceConversion,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

# ------------------------------------------------------------------ services


class _MoneyOwedByAgeRunner(Protocol):
    async def run(self, academy_id: str) -> MoneyOwedByAge: ...


class _InquiryConversionRunner(Protocol):
    async def run(
        self, academy_id: str, *, date_from: date | None = None, date_to: date | None = None
    ) -> InquiryConversion: ...


class _AttendanceRiskRunner(Protocol):
    async def run(self, academy_id: str) -> AttendanceRisk: ...


class _FamiliesLostRunner(Protocol):
    async def run(
        self, academy_id: str, *, date_from: date | None = None, date_to: date | None = None
    ) -> FamiliesLost: ...


class AdminPeopleReportServices(Protocol):
    @property
    def money_owed_by_age(self) -> _MoneyOwedByAgeRunner: ...

    @property
    def inquiry_conversion(self) -> _InquiryConversionRunner: ...

    @property
    def attendance_risk(self) -> _AttendanceRiskRunner: ...

    @property
    def families_lost(self) -> _FamiliesLostRunner: ...


def get_admin_people_reports(request: Request) -> AdminPeopleReportServices:
    services: AdminPeopleReportServices = request.app.state.admin_family_index.reports
    return services


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


# ------------------------------------------------------------------ views


class AgeBandView(BaseModel):
    key: str
    label: str
    min_days: int | None
    max_days: int | None
    family_count: int
    total_cents: int


class MoneyOwedByAgeView(BaseModel):
    as_of: date
    generated_at: datetime
    not_yet_due: AgeBandView
    bands: list[AgeBandView]
    overdue_cents: int
    overdue_family_count: int
    balance_cents: int
    owing_family_count: int


class SourceConversionView(BaseModel):
    source: str
    inquiries: int
    lead: int
    trial: int
    enrolled: int
    conversion_rate: float | None


class InquiryConversionView(BaseModel):
    date_from: date
    date_to: date
    timezone: str
    sources: list[SourceConversionView]
    total: SourceConversionView


class ClassRiskView(BaseModel):
    session_id: str
    title: str
    coach_id: str | None
    coach_name: str | None
    students: int
    at_risk: int
    at_risk_rate: float | None


class CoachRiskView(BaseModel):
    coach_id: str | None
    coach_name: str | None
    classes: int
    students: int
    at_risk: int
    at_risk_rate: float | None


class AttendanceRiskView(BaseModel):
    generated_at: datetime
    by_class: list[ClassRiskView]
    by_coach: list[CoachRiskView]
    students: int
    at_risk: int


class ReasonCountView(BaseModel):
    key: str
    label: str | None
    families: int


class FamiliesLostView(BaseModel):
    date_from: date
    date_to: date
    timezone: str
    families_lost: int
    by_reason: list[ReasonCountView]
    with_reason: int
    by_transition: list[ReasonCountView]
    without_reason: int


def _class_risk(row: ClassRiskRow) -> ClassRiskView:
    return ClassRiskView(
        session_id=row.session_id,
        title=row.title,
        coach_id=row.coach_id,
        coach_name=row.coach_name,
        students=row.students,
        at_risk=row.at_risk,
        at_risk_rate=row.at_risk_rate,
    )


def _coach_risk(row: CoachRiskRow) -> CoachRiskView:
    return CoachRiskView(
        coach_id=row.coach_id,
        coach_name=row.coach_name,
        classes=row.classes,
        students=row.students,
        at_risk=row.at_risk,
        at_risk_rate=row.at_risk_rate,
    )


def _reason(row: ReasonCount) -> ReasonCountView:
    return ReasonCountView(key=row.key, label=row.label, families=row.families)


def _band(band: AgeBandTotal) -> AgeBandView:
    return AgeBandView(
        key=band.key,
        label=band.label,
        min_days=band.min_days,
        max_days=band.max_days,
        family_count=band.family_count,
        total_cents=band.total_cents,
    )


def _source(row: SourceConversion) -> SourceConversionView:
    return SourceConversionView(
        source=row.source,
        inquiries=row.inquiries,
        lead=row.lead,
        trial=row.trial,
        enrolled=row.enrolled,
        conversion_rate=row.conversion_rate,
    )


# ------------------------------------------------------------------ routes

router = APIRouter(tags=["admin.reports.people"])


@router.get("/reports/people/money-owed-by-age", response_model=MoneyOwedByAgeView)
async def money_owed_by_age(
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPeopleReportServices = Depends(get_admin_people_reports),
) -> MoneyOwedByAgeView:
    """Open balance by days past due (1-30, 31-60, over 60) and not yet due."""
    if not can_view_family_money(claims):
        raise HTTPException(status_code=403, detail="Family money is not visible to your role")
    try:
        report = await services.money_owed_by_age.run(_academy_id(claims))
    except (FamilyIndexUnavailable, PeopleReportUnavailable) as exc:
        raise HTTPException(status_code=503, detail="money owed report unavailable") from exc
    return MoneyOwedByAgeView(
        as_of=report.as_of,
        generated_at=report.generated_at,
        not_yet_due=_band(report.not_yet_due),
        bands=[_band(band) for band in report.bands],
        overdue_cents=report.overdue_cents,
        overdue_family_count=report.overdue_family_count,
        balance_cents=report.balance_cents,
        owing_family_count=report.owing_family_count,
    )


@router.get("/reports/people/inquiry-conversion", response_model=InquiryConversionView)
async def inquiry_conversion(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPeopleReportServices = Depends(get_admin_people_reports),
) -> InquiryConversionView:
    """Inquiries by source and how many reached trial or enrolled."""
    try:
        report = await services.inquiry_conversion.run(
            _academy_id(claims), date_from=date_from, date_to=date_to
        )
    except InvalidReportRange as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return InquiryConversionView(
        date_from=report.date_from,
        date_to=report.date_to,
        timezone=report.timezone,
        sources=[_source(row) for row in report.sources],
        total=_source(report.total),
    )


@router.get("/reports/people/attendance-risk", response_model=AttendanceRiskView)
async def attendance_risk(
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPeopleReportServices = Depends(get_admin_people_reports),
) -> AttendanceRiskView:
    """Students who stopped coming (lifecycle at_risk), by class and by coach."""
    try:
        report = await services.attendance_risk.run(_academy_id(claims))
    except PeopleReportUnavailable as exc:
        raise HTTPException(status_code=503, detail="attendance risk report unavailable") from exc
    return AttendanceRiskView(
        generated_at=report.generated_at,
        by_class=[_class_risk(row) for row in report.by_class],
        by_coach=[_coach_risk(row) for row in report.by_coach],
        students=report.students,
        at_risk=report.at_risk,
    )


@router.get("/reports/people/families-lost", response_model=FamiliesLostView)
async def families_lost(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPeopleReportServices = Depends(get_admin_people_reports),
) -> FamiliesLostView:
    """Families that left in the window, by recorded reason or by how they left."""
    try:
        report = await services.families_lost.run(
            _academy_id(claims), date_from=date_from, date_to=date_to
        )
    except InvalidReportRange as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (FamilyIndexUnavailable, PeopleReportUnavailable) as exc:
        raise HTTPException(status_code=503, detail="families lost report unavailable") from exc
    return FamiliesLostView(
        date_from=report.date_from,
        date_to=report.date_to,
        timezone=report.timezone,
        families_lost=report.families_lost,
        by_reason=[_reason(row) for row in report.by_reason],
        with_reason=report.with_reason,
        by_transition=[_reason(row) for row in report.by_transition],
        without_reason=report.without_reason,
    )
