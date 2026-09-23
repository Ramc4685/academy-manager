"""Response models for the People CRM family index (``GET /admin/families*``).

People CRM spec §3.2. The shapes are the contract the Families view (A3b)
consumes:

* ``GET /admin/families`` → :class:`AdminFamilyIndexPage`: one row per
  family record, children with lifecycle chips and classes, the rolled-up
  stage, card/registration state and a ``money`` block that is ``null`` for
  callers who may not see amounts (``money_visible`` says which);
* ``GET /admin/families/summary`` → :class:`AdminFamilyIndexSummary`: the
  scope tiles over the unfiltered index, counts per stage, and the static
  view presets.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.v2.contexts.crm.application.family_index import (
    FamilyChild,
    FamilyIndexPage,
    FamilyIndexRow,
    FamilyIndexSummary,
    FamilyMoney,
    FamilyRecord,
)

FamilyStageName = Literal[
    "pending_cancel",
    "active",
    "at_risk",
    "on_hold",
    "paused",
    "trial",
    "never_enrolled",
    "left",
]


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminFamilyClass(_View):
    session_id: str
    title: str


class AdminFamilyChild(_View):
    student_id: str
    name: str
    #: The child's ``derive_lifecycle`` state (the /admin/students chip).
    lifecycle: FamilyStageName
    lifecycle_as_of: date | None = None
    classes: list[AdminFamilyClass] = Field(default_factory=list)
    #: True when the search query matched this child: the UI makes the child
    #: the result row and links to /admin/students/{id} (spec §3.2).
    matched: bool = False


class AdminFamilyMoney(_View):
    balance_cents: int
    open_invoice_count: int
    overdue_invoice_count: int
    overdue_cents: int
    oldest_overdue_due_on: date | None = None
    last_failed_payment_at: datetime | None = None


class AdminFamilyIndexRow(_View):
    #: The id ``/admin/families/{family_id}/billing`` opens.
    family_id: str
    parent_name: str | None = None
    email: str | None = None
    phone: str | None = None
    has_account: bool
    stage: FamilyStageName
    children: list[AdminFamilyChild]
    card_on_file: bool | None = None
    registration: Literal["registered", "invited", "not_invited"] | None = None
    #: Null when money is hidden from this caller or could not be read.
    money: AdminFamilyMoney | None = None
    #: True when the search matched the parent (name, email, phone).
    matched_parent: bool = False


class AdminFamilyIndexPage(_View):
    generated_at: datetime
    families: list[AdminFamilyIndexRow]
    total: int
    page: int
    page_size: int
    money_visible: bool
    warnings: list[str] = Field(default_factory=list)


class AdminFamilyRecordView(_View):
    """``GET /admin/families/{family_id}/record``: the family's index row.

    The family record page's Overview header and Details tab read this, so
    the stage, children and contact fields match the Families view exactly.
    """

    generated_at: datetime
    #: The canonical family id, whichever alias the URL carried: the page
    #: replaces an alias URL with this one.
    family_id: str
    family: AdminFamilyIndexRow
    money_visible: bool
    warnings: list[str] = Field(default_factory=list)


class AdminFamilyViewPreset(_View):
    """A static, built-in view: query params the Families view applies.

    Saved, named Groups stored per academy are Phase 4 (``family_groups``).
    """

    id: str
    label: str
    params: dict[str, str]
    money: bool = False


class AdminFamilyIndexSummary(_View):
    generated_at: datetime
    total_families: int
    tiles: dict[Literal["active", "leaving", "left"], int]
    counts_by_stage: dict[FamilyStageName, int]
    presets: list[AdminFamilyViewPreset]
    #: Families each non-scope preset chip keeps, keyed by preset id
    #: (``no_card``; ``overdue`` only when money is visible).
    preset_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


#: Static presets (spec §3.2 scope tiles and filter chips that have data
#: behind them today). ``money`` presets are hidden from callers who may not
#: see money.
VIEW_PRESETS: tuple[AdminFamilyViewPreset, ...] = (
    AdminFamilyViewPreset(id="active", label="Active", params={"scope": "active"}),
    AdminFamilyViewPreset(id="leaving", label="Leaving", params={"scope": "leaving"}),
    AdminFamilyViewPreset(id="left", label="Left", params={"scope": "left"}),
    AdminFamilyViewPreset(id="overdue", label="Overdue", params={"overdue": "true"}, money=True),
    AdminFamilyViewPreset(id="no_card", label="No card", params={"card_on_file": "false"}),
)


def _child(child: FamilyChild, matched: frozenset[str]) -> AdminFamilyChild:
    return AdminFamilyChild(
        student_id=child.student_id,
        name=child.name,
        lifecycle=child.lifecycle,
        lifecycle_as_of=child.lifecycle_as_of,
        classes=[
            AdminFamilyClass(session_id=sid, title=title)
            for sid, title in zip(child.session_ids, child.session_titles, strict=False)
        ],
        matched=child.student_id in matched,
    )


def _money(money: FamilyMoney | None, visible: bool) -> AdminFamilyMoney | None:
    if money is None or not visible:
        return None
    return AdminFamilyMoney(
        balance_cents=money.balance_cents,
        open_invoice_count=money.open_invoice_count,
        overdue_invoice_count=money.overdue_invoice_count,
        overdue_cents=money.overdue_cents,
        oldest_overdue_due_on=money.oldest_overdue_due_on,
        last_failed_payment_at=money.last_failed_payment_at,
    )


def _row(row: FamilyIndexRow, *, money_visible: bool) -> AdminFamilyIndexRow:
    record = row.record
    matched = frozenset(row.hit.matched_student_ids) if row.hit else frozenset()
    return AdminFamilyIndexRow(
        family_id=record.family_id,
        parent_name=record.parent_name,
        email=record.email,
        phone=record.phone,
        has_account=record.has_account,
        stage=record.stage,
        children=[_child(child, matched) for child in record.children],
        card_on_file=record.card_on_file,
        registration=record.registration,
        money=_money(record.money, money_visible),
        matched_parent=bool(row.hit and row.hit.matched_parent),
    )


def page_view(page: FamilyIndexPage, *, generated_at: datetime) -> AdminFamilyIndexPage:
    return AdminFamilyIndexPage(
        generated_at=generated_at,
        families=[_row(row, money_visible=page.money_visible) for row in page.rows],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        money_visible=page.money_visible,
        warnings=list(page.warnings),
    )


def _preset_counts(summary: FamilyIndexSummary, *, money_visible: bool) -> dict[str, int]:
    counts = {"no_card": summary.no_card_families}
    if money_visible:
        # Money derived: a caller who may not see money gets no Overdue count.
        counts["overdue"] = summary.overdue_families
    return counts


def summary_view(
    summary: FamilyIndexSummary, *, generated_at: datetime, money_visible: bool
) -> AdminFamilyIndexSummary:
    return AdminFamilyIndexSummary(
        generated_at=generated_at,
        total_families=summary.total_families,
        tiles=summary.tiles,
        counts_by_stage=summary.counts_by_stage,
        presets=[p for p in VIEW_PRESETS if money_visible or not p.money],
        preset_counts=_preset_counts(summary, money_visible=money_visible),
        warnings=list(summary.warnings),
    )


def record_view(
    record: FamilyRecord,
    *,
    generated_at: datetime,
    money_visible: bool,
    warnings: tuple[str, ...] = (),
) -> AdminFamilyRecordView:
    return AdminFamilyRecordView(
        generated_at=generated_at,
        family_id=record.family_id,
        family=_row(FamilyIndexRow(record=record), money_visible=money_visible),
        money_visible=money_visible,
        warnings=list(warnings),
    )
