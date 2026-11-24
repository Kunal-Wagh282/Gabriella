"""A believable purchase history for the demo shopper, so personalisation shows on first login.

Historical orders only: stock is not touched (these sales happened "months ago").
Idempotent: does nothing if the demo shopper already has orders.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Category, Order, OrderItem, Product, ProductVariant, Store, User
from app.services.profile import rebuild_profile

# (category, colour families, size) per order; a smart-casual menswear shopper who likes blue.
BASKETS = [
    [("casual-shirts", ("blue",), "M"), ("chinos", ("neutral",), "M")],
    [("polos", ("blue", "white"), "M"), ("sneakers", ("white",), "UK 9")],
    [("knitwear", ("blue", "grey"), "M"), ("chinos", ("neutral", "brown"), "M")],
    [("casual-shirts", ("white", "blue"), "M"), ("loafers", ("brown",), "UK 9")],
]


async def ensure_demo_history(session: AsyncSession) -> int:
    settings = get_settings()
    user = await session.scalar(select(User).where(User.email == settings.seed_demo_email.lower()))
    if user is None:
        return 0
    if await session.scalar(
        select(func.count()).select_from(Order).where(Order.user_id == user.id)
    ):
        return 0
    store = await session.scalar(select(Store).where(Store.code == "PUN"))
    now = datetime.now(UTC)
    used: set[int] = set()
    created = 0
    for n, basket in enumerate(BASKETS):
        order = Order(
            id=uuid.uuid4(),
            number=f"GB-DEMO-{n + 1:04d}",
            user_id=user.id,
            status="fulfilled",
            subtotal=0,
            item_count=0,
        )
        order.created_at = order.updated_at = now - timedelta(days=150 - n * 35)
        for category, families, size in basket:
            row = (
                (
                    await session.execute(
                        select(Product, ProductVariant)
                        .join(Category, Category.id == Product.category_id)
                        .join(ProductVariant, ProductVariant.product_id == Product.id)
                        .where(
                            Category.slug == category,
                            Product.gender.in_(["men", "unisex"]),
                            Product.colour_family.in_(families),
                            Product.is_active.is_(True),
                            ProductVariant.size == size,
                            Product.id.notin_(used or {0}),
                        )
                        .order_by(Product.popularity.desc(), Product.id)
                        .limit(1)
                    )
                )
                .unique()
                .first()
            )
            if row is None:
                continue
            product, variant = row
            used.add(product.id)
            order.items.append(
                OrderItem(
                    product_id=product.id,
                    variant_id=variant.id,
                    store_id=store.id,
                    quantity=1,
                    unit_price=product.price,
                    product_name=product.name,
                    size=variant.size,
                    colour=product.colour,
                )
            )
            order.subtotal += product.price
            order.item_count += 1
        if order.items:
            session.add(order)
            created += 1
    await session.flush()
    await rebuild_profile(session, user.id)
    return created
