"""Filter, search, sort and paginate the family index (People CRM spec §3.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.crm.application.family_index import (
    FamilyIndexQuery,
    normalize_stages,
    query_family_index,
    summarize_family_index,
)
from backend.v2.contexts.crm.application.money_visibility import can_view_family_money
from backend.v2.contexts.crm.domain.family_index import (
    FamilyChild,
    FamilyIndex,
    FamilyMoney,
    FamilyRecord,
    search_family,
)
from backend.v2.shared.auth.claims import AuthClaims

NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


def _money(balance: int, overdue: int = 0) -> FamilyMoney:
    return FamilyMoney(
        balance_cents=balance,
        open_invoice_count=1 if balance else 0,
        overdue_invoice_count=1 if overdue else 0,
        overdue_cents=overdue,
        oldest_overdue_due_on=date(2026, 9, 1) if overdue else None,
        last_failed_payment_at=None,
    )


def _family(
    family_id: str,
    parent: str,
    *,
    stage: str = "active",
    kids: tuple[tuple[str, str, tuple[str, ...]], ...] = (),
    email: str | None = None,
    phone: str | None = None,
    balance: int = 0,
    overdue: int = 0,
    card: bool | None = True,
    legacy: tuple[str, ...] = (),
) -> FamilyRecord:
    return FamilyRecord(
        family_id=family_id,
        parent_name=parent,
        email=email,
        phone=phone,
        has_account=True,
        children=tuple(
            FamilyChild(
                student_id=sid,
                name=name,
                lifecycle=stage,
                session_ids=sessions,
                session_titles=sessions,
            )
            for sid, name, sessions in kids
        ),
        stage=stage,  # type: ignore[arg-type]
        card_on_file=card,
        registration="registered" if card else "not_invited",
        money=_money(balance, overdue),
        legacy_contact_keys=legacy,
    )


INDEX = FamilyIndex(
    academy_id="acad-test",
    generated_at=NOW,
    families=(
        _family(
            "u-alpha",
            "Testparent Alpha",
            kids=(("s-1", "Kiddo Alpha", ("sess-sat",)),),
            email="alpha@example.test",
            phone="(555) 010-0001",
            balance=6000,
            overdue=6000,
        ),
        _family(
            "u-bravo",
            "Testparent Bravo",
            stage="paused",
            kids=(("s-2", "Zed Bravo", ("sess-wed",)), ("s-3", "Annie Bravo", ())),
            balance=2500,
            card=False,
        ),
        _family("u-charlie", "Testparent Charlie", stage="left"),
        _family("u-delta", "Testparent Delta", stage="never_enrolled", legacy=("roster guardian",)),
        _family("u-echo", "Testparent Echo", stage="pending_cancel", balance=100),
    ),
)


def _ids(page) -> list[str]:  # type: ignore[no-untyped-def]
    return [row.record.family_id for row in page.rows]


def test_default_is_every_family_by_parent_name() -> None:
    page = query_family_index(INDEX, FamilyIndexQuery(), money_visible=True)
    assert _ids(page) == ["u-alpha", "u-bravo", "u-charlie", "u-delta", "u-echo"]
    assert page.total == 5


def test_scope_tile_leaving_covers_the_leaving_stages() -> None:
    page = query_family_index(INDEX, FamilyIndexQuery(scope="leaving"), money_visible=True)
    assert _ids(page) == ["u-bravo", "u-echo"]


def test_stage_filter_and_scope_intersect() -> None:
    page = query_family_index(
        INDEX, FamilyIndexQuery(scope="leaving", stages=("paused", "left")), money_visible=True
    )
    assert _ids(page) == ["u-bravo"]
    page = query_family_index(INDEX, FamilyIndexQuery(stages=("left",)), money_visible=True)
    assert _ids(page) == ["u-charlie"]


def test_class_filter_matches_any_child_in_the_session() -> None:
    page = query_family_index(INDEX, FamilyIndexQuery(class_id="sess-wed"), money_visible=True)
    assert _ids(page) == ["u-bravo"]


def test_no_card_filter() -> None:
    page = query_family_index(INDEX, FamilyIndexQuery(card_on_file=False), money_visible=True)
    assert _ids(page) == ["u-bravo"]


def test_overdue_filter_needs_money_visibility() -> None:
    visible = query_family_index(INDEX, FamilyIndexQuery(overdue=True), money_visible=True)
    assert _ids(visible) == ["u-alpha"]
    hidden = query_family_index(INDEX, FamilyIndexQuery(overdue=True), money_visible=False)
    assert _ids(hidden) == []


def test_balance_sort_is_largest_first_and_runs_before_pagination() -> None:
    first = query_family_index(
        INDEX, FamilyIndexQuery(sort="balance", page_size=2), money_visible=True
    )
    second = query_family_index(
        INDEX, FamilyIndexQuery(sort="balance", page=2, page_size=2), money_visible=True
    )
    assert _ids(first) == ["u-alpha", "u-bravo"]
    assert _ids(second) == ["u-echo", "u-charlie"]
    assert first.total == second.total == 5


def test_balance_sort_falls_back_to_name_when_money_is_hidden() -> None:
    page = query_family_index(INDEX, FamilyIndexQuery(sort="balance"), money_visible=False)
    assert _ids(page) == ["u-alpha", "u-bravo", "u-charlie", "u-delta", "u-echo"]
    assert page.money_visible is False


def test_stage_sort_uses_family_precedence() -> None:
    page = query_family_index(INDEX, FamilyIndexQuery(sort="stage"), money_visible=True)
    assert _ids(page) == ["u-echo", "u-alpha", "u-bravo", "u-delta", "u-charlie"]


def test_search_child_first_name_prefix_names_the_child() -> None:
    page = query_family_index(INDEX, FamilyIndexQuery(search="ann"), money_visible=True)
    assert _ids(page) == ["u-bravo"]
    hit = page.rows[0].hit
    assert hit is not None and hit.matched_student_ids == ("s-3",)
    assert hit.matched_parent is False


def test_search_parent_name_email_phone_and_legacy_fields() -> None:
    def ids(q: str) -> list[str]:
        return _ids(query_family_index(INDEX, FamilyIndexQuery(search=q), money_visible=True))

    assert ids("testparent ch") == ["u-charlie"]
    assert ids("alpha@example") == ["u-alpha"]
    assert ids("555-010-0001") == ["u-alpha"]
    assert ids("0100001") == ["u-alpha"]  # last 7 digits
    assert ids("roster guard") == ["u-delta"]
    assert ids("nobody-matches") == []
    assert ids("   ") == ["u-alpha", "u-bravo", "u-charlie", "u-delta", "u-echo"]


def test_short_digit_runs_are_not_phone_searches() -> None:
    record = INDEX.families[0]
    assert search_family(record, "5550") is None


def test_summary_tiles_count_each_family_once_over_the_unfiltered_index() -> None:
    summary = summarize_family_index(INDEX)
    assert summary.total_families == 5
    assert summary.tiles == {"active": 1, "leaving": 2, "left": 1}
    assert summary.counts_by_stage["never_enrolled"] == 1
    assert sum(summary.counts_by_stage.values()) == 5


def test_normalize_stages_accepts_commas_and_repeats() -> None:
    assert normalize_stages(["active,paused", "paused", " left "]) == ("active", "paused", "left")


@pytest.mark.parametrize(
    ("roles", "visible"),
    [
        (("admin",), True),
        (("owner",), True),
        (("admin", "owner"), True),
        (("coach",), False),
        (("parent",), False),
        ((), False),
    ],
)
def test_money_seam_is_owner_or_admin_today(roles: tuple[str, ...], visible: bool) -> None:
    claims = AuthClaims(user_id="u", email="u@example.test", academy_id="a", roles=roles)  # type: ignore[arg-type]
    assert can_view_family_money(claims) is visible
