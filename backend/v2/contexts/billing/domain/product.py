"""Product catalog — lightweight per-academy priced items for invoice lines."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Product(BaseModel):
    model_config = {"frozen": True}

    product_id: str
    academy_id: str
    name: str
    default_unit_amount_cents: int = Field(ge=0)
    line_type: str  # "tuition" | "equipment" | "fee" | "adjustment" | custom
    active: bool = True
    created_at: datetime
    updated_at: datetime
