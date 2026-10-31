"""The Pipeline board read (People CRM L3b): columns, move targets, merge.

Pure over ``build_pipeline_board`` plus ``GetPipelineBoard``'s warning path.
Store behaviour (tenant scope, newest first) is proven on a real ``mongod`` in
``contract/test_crm_pipeline_board_real_mongo.py``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from backend.v2.contexts.crm.application.family_index import FamilyIndexUnavailable
from backend.v2.contexts.crm.application.pipeline_board import (
    ENROLLED_CARD_DAYS,
    GetPipelineBoard,
    build_pipeline_board,
    move_targets,
)
from backend.v2.contexts.crm.domain.family_index import FamilyChild, FamilyIndex, FamilyRecord
from backend.v2.contexts.crm.domain.models import CrmContact, PipelineOverride

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=UTC)


def _contact(cid: str, **kw: object) -> CrmContact:
    base: dict[str, object] = {
        "contact_id": cid,
        "academy_id": "acad-a",
        "name": f"Parent {cid}",
        "phone_digits": "5550100000",
        "source": "whatsapp_or_phone",
        "created_at": NOW - timedelta(days=3),
        "updated_at": NOW - timedelta(days=3),
    }
    base.update(kw)
    return CrmContact(**base)  # type: ignore[arg-type]


def _family(fid: str, stage: str, *, has_account: bool = True, child: str | None = None):
    children = (FamilyChild(student_id=f"s-{fid}", name=child, lifecycle=stage),) if child else ()
    return FamilyRecord(
        family_id=fid,
        parent_name=f"Family {fid}",
        email=None,
        phone=None,
        has_account=has_account,
        children=children,
        stage=stage,  # type: ignore[arg-type]
    )


def _index(*families: FamilyRecord, aliases: dict[str, str] | None = None) -> FamilyIndex:
    return FamilyIndex(
        academy_id="acad-a",
        generated_at=NOW,
        families=families,
        family_by_alias=aliases or {},
    )


def _by_id(board):
    return {card.card_id: card for card in board.cards}


def test_contact_columns_follow_stage_then_override() -> None:
    board = build_pipeline_board(
        [
            _contact("lead"),
            _contact("trial", pipeline_status="trial"),
            _contact(
                "moved",
                pipeline_override=PipelineOverride(
                    column="trial_done", set_by="staff-1", set_at=NOW - timedelta(hours=1)
                ),
                pipeline_status="trial",
            ),
            _contact("enr", pipeline_status="enrolled", updated_at=NOW - timedelta(days=1)),
        ],
        None,
        now=NOW,
    )
    cards = _by_id(board)
    assert cards["contact:lead"].column == "inquiry"
    assert cards["contact:trial"].column == "trial_booked"
    moved = cards["contact:moved"]
    assert moved.column == "trial_done"
    assert (moved.override_column, moved.override_set_by) == ("trial_done", "staff-1")
    assert cards["contact:enr"].column == "enrolled"
    assert cards["contact:lead"].lead_age_days == 3


def test_move_targets_forward_one_back_any_never_enrolled() -> None:
    assert move_targets("inquiry", enrolled=False) == ("trial_booked",)
    assert move_targets("trial_done", enrolled=False) == (
        "inquiry",
        "trial_booked",
        "registered",
    )
    assert move_targets("registered", enrolled=False) == ("inquiry", "trial_booked", "trial_done")
    assert move_targets("enrolled", enrolled=True) == ()


def test_enrolled_card_leaves_after_seven_days() -> None:
    board = build_pipeline_board(
        [
            _contact(
                "old",
                pipeline_status="enrolled",
                updated_at=NOW - timedelta(days=ENROLLED_CARD_DAYS, minutes=1),
            ),
            _contact("new", pipeline_status="enrolled", updated_at=NOW - timedelta(days=6)),
        ],
        None,
        now=NOW,
    )
    assert [c.card_id for c in board.cards] == ["contact:new"]
    assert board.cards[0].move_targets == ()


def test_family_cards_from_stage_roll_up_are_read_only() -> None:
    board = build_pipeline_board(
        [],
        _index(
            _family("f-trial", "trial", child="Sample Kid"),
            _family("f-lead", "never_enrolled"),
            _family("f-roster-only", "never_enrolled", has_account=False),
            _family("f-active", "active", child="Other Kid"),
            _family("f-left", "left", child="Past Kid"),
        ),
        now=NOW,
    )
    cards = _by_id(board)
    assert set(cards) == {"family:f-trial", "family:f-lead"}
    trial = cards["family:f-trial"]
    assert (trial.column, trial.child, trial.move_targets) == ("trial_booked", "Sample Kid", ())
    assert trial.family_id == "f-trial"
    assert cards["family:f-lead"].column == "inquiry"


def test_family_linked_from_a_contact_is_not_shown_twice_even_by_alias() -> None:
    board = build_pipeline_board(
        [_contact("c1", linked_family_id="alias-9")],
        _index(_family("f-1", "trial"), _family("f-2", "trial"), aliases={"alias-9": "f-1"}),
        now=NOW,
    )
    assert sorted(c.card_id for c in board.cards) == ["contact:c1", "family:f-2"]


class _Contacts:
    def __init__(self, *rows: CrmContact) -> None:
        self.rows = list(rows)
        self.limit: int | None = None

    async def list_by_pipeline_status(self, status=None, *, limit: int = 200):
        self.limit = limit
        return self.rows[:limit]


class _BrokenIndex:
    async def build(self, academy_id: str) -> FamilyIndex:
        raise FamilyIndexUnavailable("index down")


def test_failed_family_index_is_a_warning_not_an_empty_board() -> None:
    contacts = _Contacts(_contact("c1"))
    board = asyncio.run(
        GetPipelineBoard(contacts, _BrokenIndex(), clock=lambda: NOW).execute("acad-a")
    )
    assert board.warnings == ("families_unavailable",)
    assert [c.card_id for c in board.cards] == ["contact:c1"]
    assert contacts.limit == 500
