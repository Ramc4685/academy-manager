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


def _discount_line(*, line_id: str, invoice_id: str) -> InvoiceLine:
    return InvoiceLine(
        line_id=line_id,
        academy_id="acad",
        invoice_id=invoice_id,
        line_type="discount",
        description="Sibling discount",
        quantity=1,
        unit_amount_cents=-1_000,
        amount_cents=-1_000,
        source_type="tuition_discount",
        source_id="disc-1",
        category="sibling",
        discount_kind="percent",
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
        self.invoice_payment_calls: list[dict[str, object]] = []
        self.balance_payment_calls: list[dict[str, object]] = []

    async def list_invoices_for_parent(self, parent_id: str):
        return await self._repo.list_invoices_for_parent(parent_id)

    async def get_invoice_for_parent(self, *, parent_id: str, invoice_id: str):
        invoice = await self._repo.get_invoice(invoice_id)
        if invoice is None or invoice.parent_id != parent_id:
            return None
        return {"invoice": invoice, "lines": self._repo.lines_for(invoice_id)}

    async def start_invoice_payment_for_parent(
        self,
        *,
        parent_id: str,
        invoice_id: str,
        success_url: str,
        cancel_url: str,
        enroll_autopay: bool = False,
    ):
        self.invoice_payment_calls.append(
            {
                "parent_id": parent_id,
                "invoice_id": invoice_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "enroll_autopay": enroll_autopay,
            }
        )
        invoice = await self._repo.get_invoice(invoice_id)
        if invoice is None or invoice.parent_id != parent_id:
            return None
        return {
            "invoice_id": invoice_id,
            "checkout_url": "https://checkout.stripe.test/inv-a1",
        }

    async def start_balance_payment_for_parent(
        self,
        *,
        parent_id: str,
        success_url: str,
        cancel_url: str,
        enroll_autopay: bool = False,
    ):
        self.balance_payment_calls.append(
            {
                "parent_id": parent_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "enroll_autopay": enroll_autopay,
            }
        )
        return {"redirect_url": "https://checkout.stripe.test/balance"}


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
    lines = {
        "inv-a1": [
            _line(line_id="line-1", invoice_id="inv-a1"),
            _discount_line(line_id="line-discount-1", invoice_id="inv-a1"),
        ]
    }
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
def _make_client_with_use_cases(
    role: str = "parent", user_id: str = "parent-1"
) -> Iterator[tuple[TestClient, _ParentUseCases]]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role, user_id)
    use_cases = _ParentUseCases(_seed())
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases
    with TestClient(app) as client:
        yield client, use_cases


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


def test_parent_invoice_detail_includes_public_line_items() -> None:
    with _make_client() as client:
        response = client.get("/api/v2/parent/invoices/inv-a1")

    assert response.status_code == 200
    body = response.json()
    assert body["invoice_id"] == "inv-a1"
    assert len(body["lines"]) == 2
    line = body["lines"][0]
    assert line["description"] == "May tuition"
    assert line["quantity"] == 1
    assert line["unit_amount_cents"] == 12_000
    assert line["amount_cents"] == 12_000
    discount_line = body["lines"][1]
    assert discount_line["label"] == "Sibling discount"
    assert discount_line["amount_cents"] == -1_000
    assert "note" not in discount_line
    assert "category" not in discount_line
    assert "source_type" not in discount_line
    assert "source_id" not in discount_line


def test_parent_can_start_invoice_retry_checkout_for_own_invoice() -> None:
    with _make_client() as client:
        response = client.post(
            "/api/v2/parent/invoices/inv-a1/pay",
            json={
                "success_url": "https://app.example.com/parent/payments?invoice=paid",
                "cancel_url": "https://app.example.com/parent/payments?invoice=cancelled",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "invoice_id": "inv-a1",
        "redirect_url": "https://checkout.stripe.test/inv-a1",
    }


def test_parent_cannot_read_other_parents_invoice_detail() -> None:
    with _make_client() as client:
        response = client.get("/api/v2/parent/invoices/inv-b1")

    assert response.status_code == 404


def test_parent_cannot_start_invoice_retry_checkout_for_other_parent_invoice() -> None:
    with _make_client() as client:
        response = client.post(
            "/api/v2/parent/invoices/inv-b1/pay",
            json={
                "success_url": "https://app.example.com/parent/payments?invoice=paid",
                "cancel_url": "https://app.example.com/parent/payments?invoice=cancelled",
            },
        )

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


def test_parent_invoice_list_and_detail_expose_enrollment_id() -> None:
    with _make_client() as client:
        list_response = client.get("/api/v2/parent/invoices")
        detail_response = client.get("/api/v2/parent/invoices/inv-a1")

    assert list_response.status_code == 200
    assert [inv["enrollment_id"] for inv in list_response.json()["invoices"]] == [
        "enroll-1",
        "enroll-1",
    ]
    assert detail_response.status_code == 200
    assert detail_response.json()["enrollment_id"] == "enroll-1"


def test_pay_body_without_enroll_autopay_defaults_to_false() -> None:
    with _make_client_with_use_cases() as (client, use_cases):
        response = client.post(
            "/api/v2/parent/invoices/inv-a1/pay",
            json={
                "success_url": "https://app.example.com/parent/payments?invoice=paid",
                "cancel_url": "https://app.example.com/parent/payments?invoice=cancelled",
            },
        )

    assert response.status_code == 200, response.text
    assert use_cases.invoice_payment_calls[0]["enroll_autopay"] is False


def test_pay_body_with_enroll_autopay_true_forwards_true() -> None:
    with _make_client_with_use_cases() as (client, use_cases):
        response = client.post(
            "/api/v2/parent/invoices/inv-a1/pay",
            json={
                "success_url": "https://app.example.com/parent/payments?invoice=paid",
                "cancel_url": "https://app.example.com/parent/payments?invoice=cancelled",
                "enroll_autopay": True,
            },
        )

    assert response.status_code == 200, response.text
    assert use_cases.invoice_payment_calls[0]["enroll_autopay"] is True


def test_balance_pay_body_without_enroll_autopay_defaults_to_false() -> None:
    with _make_client_with_use_cases() as (client, use_cases):
        response = client.post(
            "/api/v2/parent/invoices/pay-balance",
            json={
                "success_url": "https://app.example.com/parent/payments?invoice=paid",
                "cancel_url": "https://app.example.com/parent/payments?invoice=cancelled",
            },
        )

    assert response.status_code == 200, response.text
    assert use_cases.balance_payment_calls[0]["enroll_autopay"] is False


def test_balance_pay_body_with_enroll_autopay_true_forwards_true() -> None:
    with _make_client_with_use_cases() as (client, use_cases):
        response = client.post(
            "/api/v2/parent/invoices/pay-balance",
            json={
                "success_url": "https://app.example.com/parent/payments?invoice=paid",
                "cancel_url": "https://app.example.com/parent/payments?invoice=cancelled",
                "enroll_autopay": True,
            },
        )

    assert response.status_code == 200, response.text
    assert use_cases.balance_payment_calls[0]["enroll_autopay"] is True


def test_anonymous_gets_401() -> None:
    with _anon_client() as client:
        list_response = client.get("/api/v2/parent/invoices")
        detail_response = client.get("/api/v2/parent/invoices/inv-a1")

    assert list_response.status_code == 401
    assert detail_response.status_code == 401
