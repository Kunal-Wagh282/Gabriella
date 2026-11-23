from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import SessionDep
from app.retrieval.catalogue_search import search_catalogue
from app.retrieval.similar import find_similar
from app.schemas.catalogue import (
    BrandOut,
    Facets,
    ProductDetail,
    ProductFilters,
    ProductSummary,
    SortKey,
    StoreOut,
)
from app.schemas.common import Page
from app.schemas.search import SearchPage, SimilarProduct, VariantAvailability
from app.services import catalogue
from app.services.inventory import variant_availability

router = APIRouter(tags=["catalogue"])

PageNo = Annotated[int, Query(ge=1, le=500)]
PageSize = Annotated[int, Query(ge=1, le=60)]


@router.get("/search", response_model=SearchPage)
async def search(
    session: SessionDep,
    filters: Annotated[ProductFilters, Query()],
    sort: SortKey = "relevance",
    page: PageNo = 1,
    page_size: PageSize = 24,
    explain: bool = False,
):
    """Hybrid search: parsed constraints and explicit filters in SQL, then lexical + CLIP
    vector ranking fused with RRF. `explain=true` returns per-hit rank contributions."""
    return await search_catalogue(
        session, filters.q, filters, sort=sort, page=page, page_size=page_size, explain=explain
    )


@router.get("/products", response_model=Page[ProductSummary])
async def list_products(
    session: SessionDep,
    filters: Annotated[ProductFilters, Query()],
    sort: SortKey = "featured",
    page: PageNo = 1,
    page_size: PageSize = 24,
):
    if filters.q:
        result = await search_catalogue(
            session, filters.q, filters, sort=sort, page=page, page_size=page_size
        )
        return Page(items=result.items, total=result.total, page=page, page_size=page_size)
    return await catalogue.list_products(
        session, filters, sort=sort, page=page, page_size=page_size
    )


@router.get("/products/{key}", response_model=ProductDetail)
async def get_product(key: str, session: SessionDep, store_id: int | None = None):
    """Look up by numeric ID or slug. Stock is live from the inventory table."""
    return await catalogue.get_product(session, key, store_id=store_id)


@router.get("/products/{key}/similar", response_model=list[SimilarProduct])
async def similar_products(
    key: str,
    session: SessionDep,
    filters: Annotated[ProductFilters, Query()],
    limit: Annotated[int, Query(ge=1, le=24)] = 8,
):
    """Alternatives for a product: same outfit slot, different style, ranked by CLIP text +
    image similarity. Combine with `size`, `store_id` and `in_stock=true` for
    "something like this in M at Pune"."""
    product_id = await catalogue.resolve_product_id(session, key)
    hits = await find_similar(session, product_id, filters, limit=limit)
    cards = {
        c.id: c
        for c in await catalogue.summaries(session, [h.product_id for h in hits], filters.store_id)
    }
    return [
        SimilarProduct(product=cards[h.product_id], similarity=h.similarity, reasons=h.reasons)
        for h in hits
        if h.product_id in cards
    ]


@router.get("/variants/{variant_id}/availability", response_model=VariantAvailability)
async def check_variant(variant_id: int, session: SessionDep, store_id: int | None = None):
    """Exact stock for one size, at one store and everywhere else."""
    return await variant_availability(session, variant_id, store_id)


@router.get("/catalogue/facets", response_model=Facets)
async def facets(session: SessionDep, response: Response):
    response.headers["Cache-Control"] = "public, max-age=60"
    return await catalogue.get_facets(session)


@router.get("/brands", response_model=list[BrandOut])
async def brands(session: SessionDep):
    return await catalogue.list_brands(session)


@router.get("/stores", response_model=list[StoreOut])
async def stores(session: SessionDep):
    return await catalogue.list_stores(session)
