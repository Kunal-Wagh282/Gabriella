import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.catalogue import ProductSummary
from app.schemas.common import ApiModel


class CartAdd(ApiModel):
    variant_id: int
    store_id: int | None = Field(None, description="Defaults to the online store")
    quantity: int = Field(1, ge=1, le=10)
    source: Literal["product", "chat"] = "product"


class CartAddMany(ApiModel):
    items: list[CartAdd] = Field(..., min_length=1, max_length=8)


class CartUpdate(ApiModel):
    quantity: int = Field(..., ge=1, le=10)


class CartLine(ApiModel):
    id: int
    product: ProductSummary
    variant_id: int
    size: str
    store_id: int
    store_city: str
    quantity: int
    unit_price: int
    line_total: int
    available: int
    issue: str | None = None


class CartOut(ApiModel):
    items: list[CartLine]
    item_count: int
    subtotal: int
    can_checkout: bool


class OrderLine(ApiModel):
    product_id: int
    product_slug: str | None
    image_url: str | None
    product_name: str
    size: str
    colour: str
    store_city: str
    quantity: int
    unit_price: int


class OrderOut(ApiModel):
    id: uuid.UUID
    number: str
    status: str
    subtotal: int
    item_count: int
    created_at: datetime
    items: list[OrderLine]
