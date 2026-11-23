"""Contracts between Gabriella's model, her tools and the UI.

Every product the shopper sees travels through `Recommendation`: the model may only reference
product/variant IDs, which the server validates against live stock and hydrates into cards.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["top", "bottom", "onepiece", "outerwear", "footwear", "accessory", "pick"]
GroupKind = Literal["outfit", "picks", "alternatives"]
Formality = Literal["relaxed", "smart", "formal"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionConstraints(Strict):
    """What Gabriella has learnt this conversation. Persisted and fed back each turn."""

    occasion: str | None = Field(None, max_length=40)
    budget_max: int | None = Field(None, ge=0, le=500_000)
    apparel_size: str | None = Field(None, max_length=8)
    footwear_size: str | None = Field(None, max_length=8)
    gender: Literal["men", "women"] | None = None
    colours: list[str] = Field(default_factory=list, max_length=6)
    avoid_colours: list[str] = Field(default_factory=list, max_length=6)
    formality: Formality | None = None
    notes: str | None = Field(None, max_length=200)

    @field_validator("apparel_size")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v

    @field_validator("footwear_size")
    @classmethod
    def _uk(cls, v: str | None) -> str | None:
        if not v:
            return v
        digits = "".join(ch for ch in v if ch.isdigit())
        return f"UK {int(digits)}" if digits else v


class RecommendedItem(Strict):
    product_id: int
    variant_id: int | None = None
    role: Role = "pick"
    reason: str = Field("", max_length=240)


class RecommendationGroup(Strict):
    title: str = Field(..., max_length=80)
    kind: GroupKind = "picks"
    items: list[RecommendedItem] = Field(..., max_length=8)
    note: str | None = Field(None, max_length=240)


class Recommendation(Strict):
    message: str = Field(..., max_length=1200)
    groups: list[RecommendationGroup] = Field(default_factory=list, max_length=4)
    constraints: SessionConstraints = Field(default_factory=SessionConstraints)
    follow_ups: list[str] = Field(default_factory=list, max_length=4)


# ---------------------------------------------------------------- tool inputs


class SearchFilters(Strict):
    categories: list[str] = Field(default_factory=list)
    colours: list[str] = Field(default_factory=list)
    gender: Literal["men", "women", "unisex"] | None = None
    size: str | None = None
    min_price: int | None = Field(None, ge=0)
    max_price: int | None = Field(None, ge=0)
    occasion: str | None = None
    style: str | None = None
    store_code: str | None = None
    include_out_of_stock: bool = False


class SearchCatalogueInput(Strict):
    query: str = Field("", max_length=200)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(8, ge=1, le=12)


class GetProductInput(Strict):
    product_id: int


class FindSimilarInput(Strict):
    product_id: int
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(6, ge=1, le=10)


class CheckInventoryInput(Strict):
    variant_id: int
    store_code: str | None = None
