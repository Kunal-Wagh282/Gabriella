from typing import Literal

from app.schemas.catalogue import ProductSummary
from app.schemas.common import ApiModel, Page


class InterpretationOut(ApiModel):
    kind: str
    value: str
    label: str
    phrase: str


class RetrievalInfo(ApiModel):
    mode: Literal["filter", "lexical", "hybrid"]
    match: Literal["exact", "related", "none"]
    lexical_candidates: int
    vector_candidates: int
    latency_ms: float


class HitExplanation(ApiModel):
    product_id: int
    score: float
    lexical_rank: int | None
    text_rank: int | None
    image_rank: int | None
    boosts: list[str]


class SearchPage(Page[ProductSummary]):
    query: str | None
    interpretation: list[InterpretationOut]
    """What the query parser turned into filters or ranking signals."""
    retrieval: RetrievalInfo
    explain: list[HitExplanation] | None = None


class SimilarProduct(ApiModel):
    product: ProductSummary
    similarity: float
    reasons: list[str]


class StoreAvailability(ApiModel):
    store_id: int
    store_code: str
    city: str
    is_online: bool
    on_hand: int


class VariantAvailability(ApiModel):
    variant_id: int
    product_id: int
    sku: str
    size: str
    is_active: bool
    store_id: int | None
    on_hand_at_store: int | None
    in_stock_at_store: bool | None
    stores: list[StoreAvailability]
