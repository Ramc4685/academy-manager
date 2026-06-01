from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _claims(role: str = "parent", user_id: str = "parent-1") -> AuthClaims:
    return AuthClaims(
        user_id=user_id,
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _invoice(*, invoice_id: str, parent_id: str, created_at: datetime) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad",
        parent_id=parent_id,
        student_id="student-1",
        enrollment_id="enroll-1",
        period="2026-05",
        status="open",
        subtotal_cents=12_000,
        discount_cents=0,
        total_cents=12_000,
        balance_due_cents=12_000,
        currency="usd",
        due_date=date(2026, 5, 31),
        pdf_artifact_id="artifact-1",
        created_at=created_at,
        updated_at=created_at,
    )


def _line(*, line_id: str, invoice_id: str) -> InvoiceLine:
    return InvoiceLine(
        line_id=line_id,
        academy_id="acad",
        invoice_id=invoice_id,
        line_type="tuition",
        description="May tuition",
        quantity=1,
        unit_amount_cents=12_000,
        amount_cents=12_000,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


class _FakeInvoiceRepo:
    def __init__(
        self, invoices: dict[str, LedgerInvoice], lines: dict[str, list[InvoiceLine]]
    ) -> None:
        self._invoices = invoices
        self._lines = lines

    async def list_invoices_for_parent(self, parent_id: str, *, limit: int = 100):
        rows = [inv for inv in self._invoices.values() if inv.parent_id == parent_id]
        return sorted(rows, key=lambda inv: inv.created_at, reverse=True)[:limit]

    async def get_invoice(self, invoice_id: str):
        return self._invoices.get(invoice_id)

    def lines_for(self, invoice_id: str):
        return self._lines.get(invoice_id, [])


class _ParentUseCases:
    def __init__(self, repo: _FakeInvoiceRepo) -> None:
        self._repo = repo

    async def list_invoices_for_parent(self, parent_id: str):
        return await self._repo.list_invoices_for_parent(parent_id)

    async def get_invoice_for_parent(self, *, parent_id: str, invoice_id: str):
        invoice = await self._repo.get_invoice(invoice_id)
        if invoice is None or invoice.parent_id != parent_id:
            return None
        return {"invoice": invoice, "lines": self._repo.lines_for(invoice_id)}


def _seed() -> _FakeInvoiceRepo:
    invoices = {
        "inv-a1": _invoice(
            invoice_id="inv-a1", parent_id="parent-1", created_at=datetime(2026, 5, 1, tzinfo=UTC)
        ),
        "inv-a2": _invoice(
            invoice_id="inv-a2", parent_id="parent-1", created_at=datetime(2026, 5, 10, tzinfo=UTC)
        ),
        "inv-b1": _invoice(
            invoice_id="inv-b1", parent_id="parent-2", created_at=datetime(2026, 5, 5, tzinfo=UTC)
        ),
    }
    lines = {"inv-a1": [_line(line_id="line-1", invoice_id="inv-a1")]}
    return _FakeInvoiceRepo(invoices, lines)


@contextmanager
def _make_client(role: str = "parent", user_id: str = "parent-1") -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role, user_id)
    app.dependency_overrides[get_parent_use_cases] = lambda: _ParentUseCases(_seed())
    with TestClient(app) as client:
        yield client


@contextmanager
def _anon_client() -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_parent_use_cases] = lambda: _ParentUseCases(_seed())
    with TestClient(app) as client:
        yield client


def test_parent_lists_own_invoices_newest_first() -> None:
    with _make_client() as client:
        response = client.get("/api/v2/parent/invoices")

    assert response.status_code == 200
    body = response.json()
    assert [inv["invoice_id"] for inv in body["invoices"]] == ["inv-a2", "inv-a1"]
    first = body["invoices"][0]
    assert first["total_cents"] == 12_000
    assert first["balance_due_cents"] == 12_000
    assert first["currency"] == "usd"
    assert first["pdf_url"] is None  # artifact_id is internal; no public URL yet


def test_parent_invoice_detail_includes_line_items() -> None:
    with _make_client() as client:
        response = client.get("/api/v2/parent/invoices/inv-a1")

    assert response.status_code == 200
    body = response.json()
    assert body["invoice_id"] == "inv-a1"
    assert len(body["lines"]) == 1
    line = body["lines"][0]
    assert line["description"] == "May tuition"
    assert line["quantity"] == 1
    assert line["unit_amount_cents"] == 12_000
    assert line["amount_cents"] == 12_000


def test_parent_cannot_read_other_parents_invoice_detail() -> None:
    with _make_client() as client:
        response = client.get("/api/v2/parent/invoices/inv-b1")

    assert response.status_code == 404


def test_unknown_invoice_returns_404() -> None:
    with _make_client() as client:
        response = client.get("/api/v2/parent/invoices/does-not-exist")

    assert response.status_code == 404


def test_wrong_persona_cannot_list_invoices() -> None:
    with _make_client(role="coach") as client:
        response = client.get("/api/v2/parent/invoices")
    assert response.status_code == 404

    with _make_client(role="admin") as client:
        response = client.get("/api/v2/parent/invoices/inv-a1")
    assert response.status_code == 404


def test_anonymous_gets_401() -> None:
    with _anon_client() as client:
        list_response = client.get("/api/v2/parent/invoices")
        detail_response = client.get("/api/v2/parent/invoices/inv-a1")

    assert list_response.status_code == 401
    assert detail_response.status_code == 401
