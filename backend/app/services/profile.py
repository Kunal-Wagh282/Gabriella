"""Customer style profiles: a compact, derived summary of what a shopper buys.

Rebuilt after every order. Only this summary (never the order history) reaches the stylist,
and only when the shopper has personalisation switched on for their account and the chat.
"""

import statistics
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, CustomerStyleProfile, Order, OrderItem, Product


def _top(counter: Counter, n: int) -> list[str]:
    return [k for k, _ in counter.most_common(n)]


async def rebuild_profile(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    rows = (
        (
            await db.execute(
                select(OrderItem, Product, Category.slug, Order.created_at)
                .join(Order, Order.id == OrderItem.order_id)
                .join(Product, Product.id == OrderItem.product_id)
                .join(Category, Category.id == Product.category_id)
                .where(Order.user_id == user_id, Order.status != "cancelled")
                .order_by(Order.created_at.desc())
            )
        )
        .unique()
        .all()
    )
    kept = [(i, p, c) for i, p, c, _ in rows if not i.returned]
    profile: dict[str, Any] = {}
    if kept:
        sizes = Counter(i.size for i, _, _ in kept)
        prices = sorted(i.unit_price for i, _, _ in kept)
        genders = Counter(p.gender for _, p, _ in kept if p.gender != "unisex")
        profile = {
            "items_bought": sum(i.quantity for i, _, _ in kept),
            "top_categories": _top(Counter(c for _, _, c in kept), 4),
            "favourite_colours": _top(Counter(p.colour for _, p, _ in kept), 4),
            "colour_families": _top(Counter(p.colour_family for _, p, _ in kept), 3),
            "style_tags": _top(Counter(t for _, p, _ in kept for t in p.style_tags), 4),
            "brands": _top(Counter(p.brand.name for _, p, _ in kept), 3),
            "apparel_size": next(
                (s for s, _ in sizes.most_common() if not s.startswith("UK") and s != "One Size"),
                None,
            ),
            "footwear_size": next((s for s, _ in sizes.most_common() if s.startswith("UK")), None),
            "shops_for": genders.most_common(1)[0][0] if genders else None,
            "typical_price": {
                "low": prices[len(prices) // 4],
                "median": int(statistics.median(prices)),
                "high": prices[(3 * len(prices)) // 4],
            },
            "avg_formality": round(statistics.mean(p.formality for _, p, _ in kept), 1),
            "recent_product_ids": list(dict.fromkeys(p.id for _, p, _ in kept))[:12],
            "returned_product_ids": [p.id for i, p, _ in rows_returned(rows)],
        }
    orders = len({i.order_id for i, _, _, _ in rows})
    stmt = insert(CustomerStyleProfile).values(
        user_id=user_id, profile=profile, orders_considered=orders
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[CustomerStyleProfile.user_id],
            set_={
                "profile": stmt.excluded.profile,
                "orders_considered": stmt.excluded.orders_considered,
            },
        )
    )
    await db.flush()
    return profile


def rows_returned(rows: list[Any]) -> list[tuple[OrderItem, Product]]:
    return [(i, p) for i, p, _, _ in rows if i.returned]


async def load_profile(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any] | None:
    row = await db.get(CustomerStyleProfile, user_id)
    return row.profile if row and row.profile else None


def profile_summary(profile: dict[str, Any]) -> str:
    """The few signals worth a model's tokens, as one line."""
    parts = []
    if profile.get("shops_for"):
        parts.append(f"shops {profile['shops_for']}'s")
    sizes = [s for s in (profile.get("apparel_size"), profile.get("footwear_size")) if s]
    if sizes:
        parts.append("usually buys size " + " / ".join(sizes))
    if profile.get("favourite_colours"):
        parts.append(
            "favourite colours " + ", ".join(c.lower() for c in profile["favourite_colours"][:3])
        )
    if profile.get("style_tags"):
        parts.append("style " + ", ".join(t.replace("-", " ") for t in profile["style_tags"][:3]))
    price = profile.get("typical_price")
    if price:
        parts.append(f"typically spends ₹{price['low']:,}–₹{price['high']:,} per item")
    if profile.get("brands"):
        parts.append("likes " + ", ".join(profile["brands"][:2]))
    return "; ".join(parts)
