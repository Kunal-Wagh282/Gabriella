from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel

Gender = Literal["men", "women", "unisex"]
SortKey = Literal["relevance", "featured", "newest", "price_asc", "price_desc"]


class StoreOut(ApiModel):
    id: int
    code: str
    name: str
    city: str
    address: str
    is_online: bool


class BrandOut(ApiModel):
    id: int
    slug: str
    name: str
    tagline: str
    price_tier: str


class CategoryRef(ApiModel):
    id: int
    slug: str
    name: str
    slot: str | None


class CategoryNode(CategoryRef):
    product_count: int = 0
    children: list["CategoryNode"] = []


class ImageOut(ApiModel):
    url: str
    alt: str
    kind: str


class SizeAvailability(ApiModel):
    variant_id: int
    size: str
    in_stock: bool


class ProductSummary(ApiModel):
    id: int
    slug: str
    name: str
    brand: str
    category: str
    gender: Gender
    colour: str
    colour_hex: str
    price: int
    mrp: int
    image: ImageOut | None
    sizes: list[SizeAvailability]
    in_stock: bool
    """True when any size is available at the selected store (or anywhere, if none selected)."""


class StoreStock(ApiModel):
    store_id: int
    store_code: str
    on_hand: int


class VariantOut(ApiModel):
    id: int
    sku: str
    size: str
    stock: list[StoreStock]
    available_at_selected_store: int | None = None


class ColourSibling(ApiModel):
    id: int
    slug: str
    colour: str
    colour_hex: str


class ProductDetail(ApiModel):
    id: int
    slug: str
    style_code: str
    name: str
    brand: BrandOut
    category: CategoryRef
    parent_category: CategoryRef | None
    gender: Gender
    colour: str
    colour_hex: str
    colour_family: str
    secondary_colours: list[str]
    pattern: str
    material: str
    fit: str
    style_tags: list[str]
    occasions: list[str]
    seasons: list[str]
    formality: int
    price: int
    mrp: int
    description: str
    is_active: bool
    images: list[ImageOut]
    variants: list[VariantOut]
    colourways: list[ColourSibling]
    created_at: datetime
    updated_at: datetime


class ColourFacet(ApiModel):
    name: str
    hex: str
    family: str
    count: int


class ValueCount(ApiModel):
    value: str
    count: int


class Facets(ApiModel):
    categories: list[CategoryNode]
    brands: list[ValueCount]
    colours: list[ColourFacet]
    sizes: list[str]
    genders: list[ValueCount]
    style_tags: list[ValueCount]
    occasions: list[ValueCount]
    price_min: int
    price_max: int


class ProductFilters(ApiModel):
    """Hard filters applied in SQL. Also the shape Gabriella's tools will use from Phase 3."""

    q: str | None = Field(None, max_length=120)
    category: list[str] = []
    gender: list[Gender] = []
    brand: list[str] = []
    colour: list[str] = []
    size: list[str] = []
    style: list[str] = []
    occasion: list[str] = []
    min_price: int | None = Field(None, ge=0)
    max_price: int | None = Field(None, ge=0)
    store_id: int | None = None
    in_stock: bool = False
    on_sale: bool = False
