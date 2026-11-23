"""Search endpoint orchestration: hybrid retrieval → sort → paginate → product cards."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product
from app.retrieval.search import hybrid_search
from app.schemas.catalogue import ProductFilters, SortKey
from app.schemas.search import HitExplanation, InterpretationOut, RetrievalInfo, SearchPage
from app.services.catalogue import SORTS, list_products, summaries


async def search_catalogue(
    session: AsyncSession,
    query: str | None,
    filters: ProductFilters,
    *,
    sort: SortKey = "relevance",
    page: int = 1,
    page_size: int = 24,
    explain: bool = False,
) -> SearchPage:
    query = (query or "").strip() or None
    if query is None:
        listing = await list_products(
            session,
            filters,
            sort="featured" if sort == "relevance" else sort,
            page=page,
            page_size=page_size,
        )
        return SearchPage(
            **listing.model_dump(),
            query=None,
            interpretation=[],
            retrieval=RetrievalInfo(
                mode="filter",
                match="exact" if listing.total else "none",
                lexical_candidates=0,
                vector_candidates=0,
                latency_ms=0,
            ),
        )

    outcome = await hybrid_search(session, query, filters)
    ids = [h.product_id for h in outcome.hits]
    if sort != "relevance" and ids:
        ids = list(
            (
                await session.scalars(
                    select(Product.id).where(Product.id.in_(ids)).order_by(*SORTS[sort])
                )
            ).all()
        )
    window = ids[(page - 1) * page_size : page * page_size]
    items = await summaries(session, window, filters.store_id)

    return SearchPage(
        items=items,
        total=len(ids),
        page=page,
        page_size=page_size,
        query=query,
        interpretation=[
            InterpretationOut(**i.__dict__)
            for i in (outcome.parsed.interpretations if outcome.parsed else [])
        ],
        retrieval=RetrievalInfo(
            mode=outcome.mode,
            match=outcome.match,
            lexical_candidates=outcome.lexical_count,
            vector_candidates=outcome.vector_count,
            latency_ms=outcome.latency_ms,
        ),
        explain=[
            HitExplanation(
                product_id=h.product_id,
                score=round(h.score, 5),
                lexical_rank=h.lexical_rank,
                text_rank=h.text_rank,
                image_rank=h.image_rank,
                boosts=h.boosts,
            )
            for h in outcome.hits
            if h.product_id in set(window)
        ]
        if explain
        else None,
    )
