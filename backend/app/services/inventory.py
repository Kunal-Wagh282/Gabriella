"""Stock mutations. Every change locks the row, keeps on_hand >= 0 and writes an audit movement."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InsufficientStock, NotFound
from app.core.logging import get_logger
from app.db.models import Inventory, InventoryMovement, ProductVariant, Store
from app.schemas.search import StoreAvailability, VariantAvailability

log = get_logger("gabriella.inventory")


async def variant_availability(
    session: AsyncSession, variant_id: int, store_id: int | None = None
) -> VariantAvailability:
    """Exact, live stock for one variant: the check every recommendation must pass."""
    variant = await session.get(ProductVariant, variant_id)
    if variant is None:
        raise NotFound("Variant not found")
    rows = await session.execute(
        select(Store.id, Store.code, Store.city, Store.is_online, Inventory.on_hand)
        .join(
            Inventory,
            (Inventory.store_id == Store.id) & (Inventory.variant_id == variant_id),
            isouter=True,
        )
        .where(Store.is_active.is_(True))
        .order_by(Store.is_online, Store.city)
    )
    stores = [
        StoreAvailability(store_id=s, store_code=c, city=city, is_online=online, on_hand=n or 0)
        for s, c, city, online, n in rows.all()
    ]
    at_store = next((s.on_hand for s in stores if s.store_id == store_id), 0) if store_id else None
    return VariantAvailability(
        variant_id=variant.id,
        product_id=variant.product_id,
        sku=variant.sku,
        size=variant.size,
        is_active=variant.is_active,
        store_id=store_id,
        on_hand_at_store=at_store,
        in_stock_at_store=None if store_id is None else bool(at_store) and variant.is_active,
        stores=stores,
    )


async def adjust_stock(
    session: AsyncSession,
    *,
    variant_id: int,
    store_id: int,
    delta: int,
    reason: str,
    reference: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> Inventory:
    """Apply `delta` to one variant/store row. Caller owns the transaction."""
    if await session.get(ProductVariant, variant_id) is None:
        raise NotFound("Variant not found")
    if await session.get(Store, store_id) is None:
        raise NotFound("Store not found")

    row = await session.scalar(
        select(Inventory)
        .where(Inventory.variant_id == variant_id, Inventory.store_id == store_id)
        .with_for_update()
    )
    if row is None:
        row = Inventory(variant_id=variant_id, store_id=store_id, on_hand=0)
        session.add(row)
        await session.flush()

    new_on_hand = row.on_hand + delta
    if new_on_hand < 0:
        raise InsufficientStock(
            "Not enough stock for this change",
            details={"variant_id": variant_id, "store_id": store_id, "on_hand": row.on_hand},
        )
    row.on_hand = new_on_hand
    session.add(
        InventoryMovement(
            variant_id=variant_id,
            store_id=store_id,
            delta=delta,
            on_hand_after=new_on_hand,
            reason=reason,
            reference=reference,
            actor_user_id=actor_user_id,
        )
    )
    await session.flush()
    log.info(
        "stock_adjusted",
        variant_id=variant_id,
        store_id=store_id,
        delta=delta,
        on_hand=new_on_hand,
        reason=reason,
    )
    return row
