"""'Something like this' retrieval: substitutes for a seed product.

Ranks by a blend of CLIP text and image similarity, restricted to the same outfit slot
(a shirt gets shirts and tees, not shoes), compatible gender, a different style, and
whatever stock/size/price filters the caller sets. Each hit carries human-readable reasons
Gabriella can quote without inventing anything.
"""

import time
from dataclasses import dataclass

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.metrics import SIMILAR_SECONDS
from app.db.models import Category, Product, ProductEmbedding
from app.schemas.catalogue import ProductFilters
from app.services.catalogue import apply_filters

ATTRIBUTE_BONUS = 0.02  # distance credit for matching category / colour family


@dataclass
class SimilarHit:
    product_id: int
    similarity: float
    reasons: list[str]


def _reasons(seed: Product, other: Product) -> list[str]:
    reasons: list[str] = []
    if other.category_id == seed.category_id:
        reasons.append(f"Also {seed.category.name.lower()}")
    if other.colour == seed.colour:
        reasons.append(f"Same colour ({seed.colour.lower()})")
    elif other.colour_family == seed.colour_family:
        reasons.append(f"Similar colour ({other.colour.lower()})")
    if other.material.lower() == seed.material.lower():
        reasons.append(f"Same fabric ({seed.material.lower()})")
    shared = [t for t in other.style_tags if t in seed.style_tags]
    if shared:
        reasons.append("Same vibe: " + ", ".join(t.replace("-", " ") for t in shared[:2]))
    if abs(other.price - seed.price) <= 0.25 * seed.price:
        reasons.append("Similar price")
    elif other.price < seed.price:
        reasons.append(f"₹{seed.price - other.price:,} less")
    return reasons


async def find_similar(
    session: AsyncSession,
    product_id: int,
    filters: ProductFilters,
    *,
    limit: int = 8,
) -> list[SimilarHit]:
    start = time.perf_counter()
    seed = await session.get(Product, product_id)
    if seed is None:
        raise NotFound("Product not found")

    eligible = await apply_filters(
        session,
        select(Product.id).join(Category, Category.id == Product.category_id),
        filters,
    )
    eligible = eligible.where(
        Product.style_code != seed.style_code, Category.slot == seed.category.slot
    )
    if not filters.gender and seed.gender != "unisex":
        eligible = eligible.where(or_(Product.gender == seed.gender, Product.gender == "unisex"))

    bonus = case((Product.category_id == seed.category_id, ATTRIBUTE_BONUS), else_=0) + case(
        (Product.colour_family == seed.colour_family, ATTRIBUTE_BONUS), else_=0
    )
    seed_vec = await session.get(ProductEmbedding, product_id)
    if seed_vec is not None and seed_vec.text_embedding is not None:
        d_text = ProductEmbedding.text_embedding.cosine_distance(seed_vec.text_embedding)
        d_image = (
            ProductEmbedding.image_embedding.cosine_distance(seed_vec.image_embedding)
            if seed_vec.image_embedding is not None
            else d_text
        )
        raw = 0.5 * d_text + 0.5 * func.coalesce(d_image, d_text)
        distance = raw - bonus
        await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        stmt = (
            select(Product, raw.label("d"))
            .join(ProductEmbedding, ProductEmbedding.product_id == Product.id)
            .where(Product.id.in_(eligible.scalar_subquery()))
            .order_by(distance)
            .limit(limit)
        )
    else:
        # No vectors yet: fall back to attribute similarity.
        distance = (
            1.0
            - 10 * bonus
            + func.abs(Product.price - seed.price) / func.greatest(seed.price, 1) * 0.1
        )
        stmt = (
            select(Product, distance.label("d"))
            .where(Product.id.in_(eligible.scalar_subquery()))
            .order_by(distance, Product.popularity.desc())
            .limit(limit)
        )

    rows = (await session.execute(stmt)).unique().all()
    SIMILAR_SECONDS.observe(time.perf_counter() - start)
    return [
        SimilarHit(
            product_id=p.id,
            similarity=round(max(0.0, min(1.0, 1 - float(d))), 3),
            reasons=_reasons(seed, p),
        )
        for p, d in rows
    ]
