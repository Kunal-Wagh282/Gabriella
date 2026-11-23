"""Hybrid catalogue retrieval.

    eligible  = SQL hard filters (active, category, colour, gender, size, price, stock@store)
    lexical   = Postgres full-text rank within eligible
    semantic  = CLIP query vector vs product text vectors AND product image vectors
    fused     = Reciprocal Rank Fusion of the three lists + soft occasion/style boosts

Vectors only ever reorder products that already passed the SQL filters, so ranking can never
surface something that's out of stock at the selected store.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Literal

from anyio import to_thread
from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.metrics import RETRIEVAL_SECONDS, SEARCH_RESULTS
from app.db.models import Product, ProductEmbedding
from app.ml.embeddings import embed_query
from app.retrieval.query_parser import ParsedQuery, parse_query
from app.retrieval.vocabulary import OCCASION_SYNONYMS, QUERY_STOPWORDS, SYNONYMS
from app.schemas.catalogue import ProductFilters
from app.services.catalogue import apply_filters

log = get_logger("gabriella.search")

RRF_K = 60
CANDIDATES = 150
WEIGHTS = {"lexical": 1.0, "text_vector": 1.0, "image_vector": 0.6}
OCCASION_BOOST = 0.012
STYLE_BOOST = 0.006
# Vector hits further than this below the best cosine similarity are treated as noise.
VECTOR_RELATIVE_CUTOFF = 0.04
VECTOR_CANDIDATES = 60
VECTOR_RANK_LIMIT = 500

Mode = Literal["filter", "lexical", "hybrid"]
MatchQuality = Literal["exact", "related", "none"]


@dataclass
class Hit:
    product_id: int
    score: float = 0.0
    lexical_rank: int | None = None
    text_rank: int | None = None
    image_rank: int | None = None
    boosts: list[str] = field(default_factory=list)


@dataclass
class SearchOutcome:
    hits: list[Hit]
    parsed: ParsedQuery | None
    filters: ProductFilters
    mode: Mode
    match: MatchQuality
    lexical_count: int = 0
    vector_count: int = 0
    latency_ms: float = 0.0


def merge_filters(base: ProductFilters, parsed: ParsedQuery) -> ProductFilters:
    """Parsed constraints fill gaps; anything the shopper set explicitly wins."""
    return base.model_copy(
        update={
            "q": None,
            "category": base.category or parsed.categories,
            "colour": base.colour or parsed.colours,
            "gender": base.gender or parsed.genders,
            "size": base.size or parsed.sizes,
            "min_price": base.min_price if base.min_price is not None else parsed.min_price,
            "max_price": base.max_price if base.max_price is not None else parsed.max_price,
            "on_sale": base.on_sale or parsed.on_sale,
        }
    )


def tsquery_text(free_text: str, *, expand: bool = True) -> str | None:
    """OR-query of lexemes (plus domain synonyms) so partial matches still rank."""
    tokens = [t for t in re.findall(r"[a-z0-9]+", free_text.lower()) if t not in QUERY_STOPWORDS]
    expanded: list[str] = []
    for t in tokens:
        expanded.append(t)
        for syn in SYNONYMS.get(t, []) if expand else []:
            expanded += re.findall(r"[a-z0-9]+", syn)
    unique = list(dict.fromkeys(t for t in expanded if len(t) > 1))
    return " | ".join(unique) if unique else None


def rrf(rank: int | None, weight: float) -> float:
    return 0.0 if rank is None else weight / (RRF_K + rank)


async def _eligible(session: AsyncSession, filters: ProductFilters) -> Select:
    return await apply_filters(session, select(Product.id), filters)


async def _lexical(session: AsyncSession, eligible: Select, query: str) -> list[int]:
    tsq = func.to_tsquery("english", query)
    rank = func.ts_rank_cd(Product.search_document, tsq, 32)
    rows = await session.execute(
        select(Product.id)
        .where(Product.id.in_(eligible.scalar_subquery()), Product.search_document.op("@@")(tsq))
        .order_by(rank.desc(), Product.popularity.desc())
        .limit(CANDIDATES)
    )
    return [r[0] for r in rows.all()]


async def _vector(
    session: AsyncSession, eligible: Select, vector: list[float], column: str
) -> tuple[list[int], set[int]]:
    """Rank every eligible product by cosine similarity.

    Returns (full ranking, products close enough to enter the result set on vector evidence
    alone). Ranking everything lets lexical hits keep their semantic credit even when they
    fall outside the vector shortlist.
    """
    col = getattr(ProductEmbedding, column)
    distance = col.cosine_distance(vector)
    # Filtered HNSW: keep scanning until enough rows pass the WHERE clause.
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    await session.execute(text("SET LOCAL hnsw.ef_search = 400"))
    rows = (
        await session.execute(
            select(ProductEmbedding.product_id, distance.label("d"))
            .where(ProductEmbedding.product_id.in_(eligible.scalar_subquery()), col.is_not(None))
            .order_by(distance)
            .limit(VECTOR_RANK_LIMIT)
        )
    ).all()
    if not rows:
        return [], set()
    best = 1 - rows[0].d
    shortlist = {
        pid for pid, d in rows[:VECTOR_CANDIDATES] if (1 - d) >= best - VECTOR_RELATIVE_CUTOFF
    }
    return [pid for pid, _ in rows], shortlist


def semantic_text(free_text: str) -> str:
    """Free text with filler removed and occasion words translated, for the CLIP encoder."""
    tokens = [t for t in re.findall(r"[a-z0-9'-]+", free_text.lower()) if t not in QUERY_STOPWORDS]
    extra = [syn for t in tokens for syn in OCCASION_SYNONYMS.get(t, []) if syn not in tokens]
    return " ".join(tokens + list(dict.fromkeys(extra))) or free_text


async def has_embeddings(session: AsyncSession) -> bool:
    return bool(await session.scalar(select(func.count()).select_from(ProductEmbedding).limit(1)))


async def hybrid_search(
    session: AsyncSession,
    query: str | None,
    filters: ProductFilters,
    *,
    parse: bool = True,
) -> SearchOutcome:
    start = time.perf_counter()
    parsed = (
        parse_query(query)
        if (query and parse)
        else (ParsedQuery(raw=query, text=query) if query else None)
    )
    effective = merge_filters(filters, parsed) if parsed else filters.model_copy(update={"q": None})
    eligible = await _eligible(session, effective)

    free_text = parsed.text if parsed else ""
    if not free_text:
        ids = (
            (await session.execute(eligible.order_by(Product.popularity.desc(), Product.id)))
            .scalars()
            .all()
        )
        outcome = SearchOutcome(
            hits=[Hit(pid) for pid in ids],
            parsed=parsed,
            filters=effective,
            mode="filter",
            match="exact" if ids else "none",
        )
        return _finish(outcome, start)

    hits: dict[int, Hit] = {}
    lexical_ids: list[int] = []
    if tsq := tsquery_text(free_text):
        lexical_ids = await _lexical(session, eligible, tsq)
    for rank, pid in enumerate(lexical_ids, 1):
        hits.setdefault(pid, Hit(pid)).lexical_rank = rank
    # "Exact" only when the shopper's own words match, not just our synonym expansions.
    literal = tsquery_text(free_text, expand=False)
    literal_match = (
        bool(lexical_ids)
        and literal is not None
        and bool(
            await session.scalar(
                select(func.count())
                .select_from(Product)
                .where(
                    Product.id.in_(eligible.scalar_subquery()),
                    Product.search_document.op("@@")(func.to_tsquery("english", literal)),
                )
            )
        )
    )

    mode: Mode = "lexical"
    vector_count = 0
    if await has_embeddings(session):
        try:
            vector = await to_thread.run_sync(embed_query, semantic_text(free_text))
        except Exception:  # noqa: BLE001 - model unavailable: degrade to lexical-only
            log.warning("query_embedding_failed", exc_info=True)
        else:
            mode = "hybrid"
            columns = (("text_embedding", "text_rank"), ("image_embedding", "image_rank"))
            ranked: dict[str, list[int]] = {}
            admitted: set[int] = set()
            for column, _ in columns:
                ranked[column], shortlist = await _vector(session, eligible, vector, column)
                admitted |= shortlist
            vector_count = len(admitted)
            for pid in admitted:
                hits.setdefault(pid, Hit(pid))
            for column, attr in columns:
                for rank, pid in enumerate(ranked[column], 1):
                    if pid in hits:
                        setattr(hits[pid], attr, rank)

    if hits:
        attrs = await session.execute(
            select(Product.id, Product.occasions, Product.style_tags, Product.popularity).where(
                Product.id.in_(hits)
            )
        )
        popularity: dict[int, int] = {}
        for pid, occasions, styles, pop in attrs.all():
            hit = hits[pid]
            hit.score = (
                rrf(hit.lexical_rank, WEIGHTS["lexical"])
                + rrf(hit.text_rank, WEIGHTS["text_vector"])
                + rrf(hit.image_rank, WEIGHTS["image_vector"])
            )
            if parsed and (matched := set(parsed.occasions) & set(occasions)):
                hit.score += OCCASION_BOOST
                hit.boosts.append("occasion:" + ",".join(sorted(matched)))
            if parsed and (matched := set(parsed.styles) & set(styles)):
                hit.score += STYLE_BOOST
                hit.boosts.append("style:" + ",".join(sorted(matched)))
            popularity[pid] = pop
        ordered = sorted(hits.values(), key=lambda h: (-h.score, -popularity.get(h.product_id, 0)))
    else:
        ordered = []

    outcome = SearchOutcome(
        hits=ordered,
        parsed=parsed,
        filters=effective,
        mode=mode,
        match="exact" if literal_match else ("related" if ordered else "none"),
        lexical_count=len(lexical_ids),
        vector_count=vector_count,
    )
    return _finish(outcome, start)


def _finish(outcome: SearchOutcome, start: float) -> SearchOutcome:
    outcome.latency_ms = round((time.perf_counter() - start) * 1000, 1)
    RETRIEVAL_SECONDS.labels(mode=outcome.mode).observe(outcome.latency_ms / 1000)
    SEARCH_RESULTS.labels(match=outcome.match).inc()
    log.info(
        "search",
        query=outcome.parsed.raw if outcome.parsed else None,
        mode=outcome.mode,
        match=outcome.match,
        hits=len(outcome.hits),
        lexical=outcome.lexical_count,
        vector=outcome.vector_count,
        latency_ms=outcome.latency_ms,
    )
    return outcome
