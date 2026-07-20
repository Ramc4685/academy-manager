"""Contract test for the parent daily digest data provider (Slice 3).

Exercises ``_ParentDigestProvider.build_view`` — the cross-context assembly that
lives at the composition root — with in-memory fakes for every collaborator. It
verifies the happy-path Variant A view, the two ``None`` cases (no children / no
session today), and that a single failing sub-lookup degrades gracefully instead
of aborting the whole view.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from backend.v2.composition import digests as digests_module
from backend.v2.composition.digests import _ParentDigestProvider
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_ID = "acad-1"
ON_DATE = date(2026, 7, 16)  # a Thursday


def _fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        frontend_url="https://app.test",
        sender_email="noreply@app.test",
        email_delivery_enabled=False,
        resend_api_key=None,
    )


def _build_provider(
    *,
    children: list,
    enrollments: list,
    occurrences: list,
    session: object | None,
    levels: list,
    focus_next_skill: object | None,
    placement: object | None,
    invoices: list,
    consents: list,
    user_doc: dict | None,
    academy_doc: dict | None,
) -> _ParentDigestProvider:
    students = SimpleNamespace(
        list_for_parent=AsyncMock(return_value=children),
        get_parent_user_doc=AsyncMock(return_value=user_doc),
    )
    enrollments_repo = SimpleNamespace(active_for_student=AsyncMock(return_value=enrollments))
    occurrences_repo = SimpleNamespace(list_for_session_between=AsyncMock(return_value=occurrences))
    sessions_repo = SimpleNamespace(get=AsyncMock(return_value=session))
    levels_repo = SimpleNamespace(list_for_program=AsyncMock(return_value=levels))
    curriculum = SimpleNamespace(
        resolve_default_program=SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(program_id="prog-1"))
        ),
        get_program=SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(name="Badminton"))
        ),
    )
    focus_students = (
        [SimpleNamespace(student_id="s1", next_skill=focus_next_skill)]
        if focus_next_skill is not None
        else []
    )
    teaching_focus = SimpleNamespace(
        for_students=AsyncMock(
            return_value=SimpleNamespace(groups=[SimpleNamespace(students=focus_students)])
        )
    )
    pathway_placement = SimpleNamespace(execute=AsyncMock(return_value=placement))
    ledger = SimpleNamespace(list_invoices_for_parent=AsyncMock(return_value=invoices))
    autopay = SimpleNamespace(list_for_parent=AsyncMock(return_value=consents))
    academies = SimpleNamespace(find_by_id=AsyncMock(return_value=academy_doc))

    return _ParentDigestProvider(
        students=students,
        enrollments=enrollments_repo,
        occurrences=occurrences_repo,
        sessions=sessions_repo,
        levels=levels_repo,
        curriculum=curriculum,
        teaching_focus=teaching_focus,
        pathway_placement=pathway_placement,
        ledger=ledger,
        autopay_consents=autopay,
        academies=academies,
    )


def _full_family_provider(**overrides) -> _ParentDigestProvider:
    kwargs = dict(
        children=[SimpleNamespace(student_id="s1", full_name="Maithri")],
        enrollments=[SimpleNamespace(session_id="sess-1")],
        occurrences=[
            SimpleNamespace(
                start_at=datetime(2026, 7, 16, 23, 0, tzinfo=UTC),
                end_at=datetime(2026, 7, 16, 23, 45, tzinfo=UTC),
                status="scheduled",
            )
        ],
        session=SimpleNamespace(title="Beginner", location="YWCA", timezone="America/Chicago"),
        levels=[
            SimpleNamespace(sequence=1),
            SimpleNamespace(sequence=2),
            SimpleNamespace(sequence=3),
        ],
        focus_next_skill=SimpleNamespace(name="Thumb grip", status="LEARNING"),
        placement=SimpleNamespace(
            skills_total=6, skills_completed=2, level_sequence=1, level_name="Level 1"
        ),
        invoices=[
            SimpleNamespace(balance_due_cents=6000, status="open", due_date=date(2026, 7, 10))
        ],
        consents=[],
        user_doc={"display_name": "Parent One", "email_verified": True},
        academy_doc={"contact_email": "ops@acad.test"},
    )
    kwargs.update(overrides)
    return _build_provider(**kwargs)


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch):
    monkeypatch.setattr(digests_module, "get_settings", _fake_settings)


@pytest.mark.asyncio
async def test_build_view_assembles_variant_a_family() -> None:
    provider = _full_family_provider()

    with tenant_scope(ACADEMY_ID):
        view = await provider.build_view("p1", ON_DATE)

    assert view is not None
    assert view.parent_name == "Parent One"
    assert view.date_label == "Thursday, July 16"
    assert view.program_name == "Badminton"
    assert view.on_portal is True  # email_verified -> Variant A
    assert len(view.children) == 1

    child = view.children[0]
    assert child.child_name == "Maithri"
    assert child.session_time == "6:00 - 6:45 PM"  # 23:00-23:45 UTC in America/Chicago
    assert child.session_label == "Beginner @ YWCA"
    assert child.focus_skill == "Thumb grip"
    assert child.focus_status == "learning"  # lowercased, underscores->spaces
    assert child.level_name == "Level 1"
    assert child.skills_completed == 2
    assert child.skills_total == 6
    assert child.skills_left == 4
    assert child.levels_to_go == 2  # sequences 2 and 3 are ahead of level 1
    assert child.cant_make_it_url == "https://app.test/parent/requests"

    assert view.dues is not None
    assert view.dues.amount == "$60.00"
    assert view.dues.due_date == "July 10"
    assert view.dues.pay_url == "https://app.test/parent/payments"
    assert view.autopay_enabled is False  # no consents -> nudge shown
    assert view.portal_url == "https://app.test/parent/dashboard"
    assert view.reply_to == "ops@acad.test"


@pytest.mark.asyncio
async def test_build_view_returns_none_when_no_children() -> None:
    provider = _full_family_provider(children=[])

    with tenant_scope(ACADEMY_ID):
        view = await provider.build_view("p1", ON_DATE)

    assert view is None


@pytest.mark.asyncio
async def test_build_view_returns_none_when_no_session_today() -> None:
    provider = _full_family_provider(occurrences=[])

    with tenant_scope(ACADEMY_ID):
        view = await provider.build_view("p1", ON_DATE)

    assert view is None


@pytest.mark.asyncio
async def test_build_view_variant_b_when_never_signed_in() -> None:
    provider = _full_family_provider(
        user_doc={"display_name": "Parent One"},  # no email_verified / last-login signal
        consents=[SimpleNamespace(consent_id="c1")],
    )

    with tenant_scope(ACADEMY_ID):
        view = await provider.build_view("p1", ON_DATE)

    assert view is not None
    assert view.on_portal is False
    assert view.children[0].cant_make_it_url is None  # no portal to deep-link into
    assert view.activate_url == "https://app.test/parent/login?continue=/parent/payments"


@pytest.mark.asyncio
async def test_build_view_degrades_when_progress_lookup_fails() -> None:
    provider = _full_family_provider()
    # Force the pathway-placement lookup to raise; the view must still render with
    # a hidden progress block (skills_total=0) rather than aborting.
    provider._pathway_placement.execute = AsyncMock(side_effect=RuntimeError("boom"))

    with tenant_scope(ACADEMY_ID):
        view = await provider.build_view("p1", ON_DATE)

    assert view is not None
    assert view.children[0].skills_total == 0
    assert view.children[0].session_time == "6:00 - 6:45 PM"  # unrelated data intact
