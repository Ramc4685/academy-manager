"""Admin billing products routes — product catalog CRUD."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.v2.contexts.billing.domain.product import Product
from backend.v2.contexts.billing.infrastructure.mongo_product_repo import MongoProductRepository
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import current_academy_id

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


def _get_product_repo(request: Request) -> MongoProductRepository:
    return MongoProductRepository(request.app.state.db)


def _product_view(product: Product) -> ProductView:
    return ProductView(
        product_id=product.product_id,
        name=product.name,
        default_unit_amount_cents=product.default_unit_amount_cents,
        line_type=product.line_type,
        active=product.active,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


# --- Routes ---


@router.get("/billing/products", response_model=ProductListResponse)
async def list_billing_products(
    _claims: AuthClaims = Depends(require_persona("admin")),
    repo: MongoProductRepository = Depends(_get_product_repo),
) -> ProductListResponse:
    products = await repo.list_products(active_only=True)
    return ProductListResponse(products=[_product_view(p) for p in products])


@router.post(
    "/billing/products",
    response_model=ProductView,
    status_code=status.HTTP_201_CREATED,
)
async def create_billing_product(
    body: CreateProductRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    repo: MongoProductRepository = Depends(_get_product_repo),
) -> ProductView:
    now = datetime.now(UTC)
    product = Product(
        product_id=f"prod-{new_ulid()}",
        academy_id=current_academy_id(),
        name=body.name,
        default_unit_amount_cents=body.default_unit_amount_cents,
        line_type=body.line_type,
        active=True,
        created_at=now,
        updated_at=now,
    )
    created = await repo.create_product(product)
    return _product_view(created)


@router.patch("/billing/products/{product_id}", response_model=ProductView)
async def update_billing_product(
    product_id: str,
    body: UpdateProductRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    repo: MongoProductRepository = Depends(_get_product_repo),
) -> ProductView:
    existing = await repo.get_product(product_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="product not found")
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return _product_view(existing)
    updated = await repo.update_product(product_id, **updates)
    return _product_view(updated)


@router.delete("/billing/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_billing_product(
    product_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    repo: MongoProductRepository = Depends(_get_product_repo),
) -> None:
    existing = await repo.get_product(product_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="product not found")
    await repo.deactivate_product(product_id)
