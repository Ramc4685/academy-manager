"""Admin billing products routes — product catalog CRUD."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.billing.products"])


# --- Request / Response DTOs ---


class CreateProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    default_unit_amount_cents: int = Field(ge=0)
    line_type: str = Field(min_length=1, max_length=50)


class UpdateProductRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    default_unit_amount_cents: int | None = Field(default=None, ge=0)
    line_type: str | None = Field(default=None, min_length=1, max_length=50)
    active: bool | None = None


class ProductView(BaseModel):
    product_id: str
    name: str
    default_unit_amount_cents: int
    line_type: str
    active: bool
    created_at: datetime
    updated_at: datetime


class ProductListResponse(BaseModel):
    products: list[ProductView]


def _required_callable(use_case: object | None, name: str) -> object:
    if use_case is None:
        raise HTTPException(status_code=503, detail=f"{name} is not configured")
    return use_case


def _product_view(product: dict[str, object]) -> ProductView:
    return ProductView(
        product_id=str(product["product_id"]),
        name=str(product["name"]),
        default_unit_amount_cents=int(product["default_unit_amount_cents"]),
        line_type=str(product["line_type"]),
        active=bool(product["active"]),
        created_at=product["created_at"],  # type: ignore[arg-type]
        updated_at=product["updated_at"],  # type: ignore[arg-type]
    )


# --- Routes ---


@router.get("/billing/products", response_model=ProductListResponse)
async def list_billing_products(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ProductListResponse:
    list_products = _required_callable(use_cases.list_billing_products, "Billing products")
    products = await list_products()  # type: ignore[operator]
    return ProductListResponse(products=[_product_view(p) for p in products])


@router.post(
    "/billing/products",
    response_model=ProductView,
    status_code=status.HTTP_201_CREATED,
)
async def create_billing_product(
    body: CreateProductRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ProductView:
    create_product = _required_callable(use_cases.create_billing_product, "Billing products")
    created = await create_product(  # type: ignore[operator]
        name=body.name,
        default_unit_amount_cents=body.default_unit_amount_cents,
        line_type=body.line_type,
    )
    return _product_view(created)


@router.patch("/billing/products/{product_id}", response_model=ProductView)
async def update_billing_product(
    product_id: str,
    body: UpdateProductRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ProductView:
    updates = body.model_dump(exclude_unset=True)
    update_product = _required_callable(use_cases.update_billing_product, "Billing products")
    if not updates:
        products = await _required_callable(
            use_cases.list_billing_products,
            "Billing products",
        )()  # type: ignore[operator]
        for product in products:
            if product["product_id"] == product_id:
                return _product_view(product)
        raise HTTPException(status_code=404, detail="product not found")
    try:
        updated = await update_product(product_id, **updates)  # type: ignore[operator]
    except ValueError as exc:
        if "not found" in str(exc):
            raise HTTPException(status_code=404, detail="product not found") from exc
        raise
    return _product_view(updated)


@router.delete("/billing/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_billing_product(
    product_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    deactivate_product = _required_callable(
        use_cases.deactivate_billing_product, "Billing products"
    )
    try:
        await deactivate_product(product_id)  # type: ignore[operator]
    except ValueError as exc:
        if "not found" in str(exc):
            raise HTTPException(status_code=404, detail="product not found") from exc
        raise
