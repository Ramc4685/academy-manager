"""Family index reads per staff tier (L2b, #553).

Owner decision 2026-09-22: owner, admin and billing see family money
amounts; front desk sees an "owes money" flag only. The redaction is done by
the server, so these tests read the raw API payload for every role and hold
that a front-desk payload carries no amount field anywhere, at any depth.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.tests.interface.test_admin_family_index_routes import FakeServices, _client

_ROUTES = (
    "/api/v2/admin/families",
    "/api/v2/admin/families/summary",
    "/api/v2/admin/families/u-alpha/record",
)

#: Keys that carry, or are derived only from, a money amount.
_AMOUNT_KEYS = frozenset(
    {
        "money",
        "balance_cents",
        "overdue_cents",
        "open_invoice_count",
        "overdue_invoice_count",
        "oldest_overdue_due_on",
        "last_failed_payment_at",
        "total_cents",
        "amount_cents",
    }
)


def _amount_values(payload: Any, path: str = "$") -> list[str]:
    """Every non-null amount-shaped value in the payload, with its JSON path."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            here = f"{path}.{key}"
            # A preset's ``money: false`` marker is a boolean, not an amount.
            amount_key = key in _AMOUNT_KEYS or key.endswith("_cents")
            if amount_key and value is not None and not isinstance(value, bool):
                found.append(here)
            found.extend(_amount_values(value, here))
    elif isinstance(payload, list):
        for i, value in enumerate(payload):
            found.extend(_amount_values(value, f"{path}[{i}]"))
    return found


def _get(roles: tuple[str, ...], path: str, **params: str) -> Any:
    with _client(roles, FakeServices()) as client:
        res = client.get(path, params=params)
    assert res.status_code == 200, (roles, path, res.text)
    return res.json()


@pytest.mark.parametrize("roles", [("owner",), ("admin",), ("billing",), ("owner", "admin")])
def test_amount_tiers_see_amounts_and_the_flag(roles: tuple[str, ...]) -> None:
    page = _get(roles, "/api/v2/admin/families")
    assert page["money_view"] == "amounts"
    assert page["money_visible"] is True
    alpha = page["families"][0]
    assert alpha["money"]["balance_cents"] == 6000
    assert alpha["owes_money"] is True
    record = _get(roles, "/api/v2/admin/families/u-alpha/record")
    assert record["money_view"] == "amounts"
    assert record["family"]["money"]["balance_cents"] == 6000
    assert record["family"]["owes_money"] is True
    summary = _get(roles, "/api/v2/admin/families/summary")
    assert "overdue" in [p["id"] for p in summary["presets"]]


@pytest.mark.parametrize("path", _ROUTES)
def test_front_desk_payload_carries_no_amount(path: str) -> None:
    body = _get(("front_desk",), path)
    assert _amount_values(body) == []
    # Also under the money sort and filter, which must not order or narrow
    # rows by a hidden amount.
    if path == "/api/v2/admin/families":
        assert _amount_values(_get(("front_desk",), path, sort="balance")) == []


def test_front_desk_gets_the_owes_money_flag_only() -> None:
    page = _get(("front_desk",), "/api/v2/admin/families")
    assert page["money_view"] == "flag"
    assert page["money_visible"] is False
    alpha, bravo = page["families"]
    assert alpha["money"] is None and alpha["owes_money"] is True
    # Bravo's money could not be read: unknown, never "does not owe".
    assert bravo["money"] is None and bravo["owes_money"] is None

    record = _get(("front_desk",), "/api/v2/admin/families/u-alpha/record")
    assert record["money_view"] == "flag"
    assert record["family"]["money"] is None
    assert record["family"]["owes_money"] is True


def test_front_desk_cannot_sort_or_filter_by_amount() -> None:
    by_balance = _get(("front_desk",), "/api/v2/admin/families", sort="balance")
    assert [f["family_id"] for f in by_balance["families"]] == ["u-alpha", "u-bravo"]
    overdue = _get(("front_desk",), "/api/v2/admin/families", overdue="true")
    assert overdue["families"] == []
    summary = _get(("front_desk",), "/api/v2/admin/families/summary")
    assert "overdue" not in [p["id"] for p in summary["presets"]]
    assert "overdue" not in summary["preset_counts"]


def test_front_desk_with_a_money_role_sees_amounts() -> None:
    """Roles are additive: front desk plus billing is billing."""
    page = _get(("front_desk", "billing"), "/api/v2/admin/families")
    assert page["money_view"] == "amounts"
    assert page["families"][0]["money"]["balance_cents"] == 6000


def test_a_paid_up_family_is_flagged_as_not_owing(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from backend.v2.tests.interface import test_admin_family_index_routes as base

    original = base._index

    def paid_up(academy_id: str) -> Any:
        index = original(academy_id)
        alpha = index.families[0]
        assert alpha.money is not None
        paid = replace(alpha, money=replace(alpha.money, balance_cents=0))
        return replace(index, families=(paid, *index.families[1:]))

    monkeypatch.setattr(base, "_index", paid_up)
    page = _get(("front_desk",), "/api/v2/admin/families")
    assert page["families"][0]["owes_money"] is False
    assert _amount_values(page) == []


@pytest.mark.parametrize("path", _ROUTES)
@pytest.mark.parametrize("roles", [("coach",), ("assistant_coach",), ("parent",), ()])
def test_no_staff_tier_is_404(roles: tuple[str, ...], path: str) -> None:
    services = FakeServices()
    with _client(roles, services) as client:
        assert client.get(path).status_code == 404
    assert services.index.calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v2/admin/families/u-alpha/billing"),
        ("GET", "/api/v2/admin/families/u-alpha/notes"),
        ("GET", "/api/v2/admin/reports/people/money-owed-by-age"),
        ("POST", "/api/v2/admin/billing/invoices/inv-1/record-payment"),
    ],
)
def test_front_desk_opens_no_other_crm_or_money_route(method: str, path: str) -> None:
    with _client(("front_desk",), FakeServices()) as client:
        assert client.request(method, path, json={}).status_code == 404
