"""Bag and simulated checkout.

Stock is the source of truth throughout: adding to the bag checks live stock at the chosen
store, and checkout locks every affected inventory row (in a fixed order, so concurrent
checkouts can't deadlock), re-checks it, decrements it with an audited `sale` movement and
writes the order, all in one transaction. Selling an item never touches its embeddings.
"""

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, InsufficientStock, NotFound
from app.core.logging import get_logger
from app.db.models import (
    Cart,
    CartItem,
    Inventory,
    Order,
    OrderItem,
    Product,
    ProductImage,
    ProductVariant,
    Store,
    User,
)
from app.schemas.commerce import CartLine, CartOut, OrderLine, OrderOut
from app.services.catalogue import summaries
from app.services.inventory import adjust_stock

log = get_logger("gabriella.commerce")


class EmptyCart(AppError):
    status_code = 400
    code = "empty_cart"


async def get_cart(db: AsyncSession, user: User) -> Cart:
    cart = await db.scalar(select(Cart).where(Cart.user_id == user.id))
    if cart is None:
        cart = Cart(user_id=user.id, items=[])  # initialised: async sessions cannot lazy-load
        db.add(cart)
        await db.flush()
    return cart


async def _store_or_online(db: AsyncSession, store_id: int | None) -> Store:
    store = (
        await db.get(Store, store_id)
        if store_id
        else await db.scalar(select(Store).where(Store.is_online.is_(True)))
    )
    if store is None or not store.is_active:
        raise NotFound("Store not found")
    return store


async def _on_hand(db: AsyncSession, variant_id: int, store_id: int) -> int:
    return (
        await db.scalar(
            select(Inventory.on_hand).where(
                Inventory.variant_id == variant_id, Inventory.store_id == store_id
            )
        )
        or 0
    )


async def add_item(
    db: AsyncSession,
    user: User,
    *,
    variant_id: int,
    store_id: int | None,
    quantity: int,
    source: str,
) -> None:
    variant = await db.get(ProductVariant, variant_id)
    if variant is None or not variant.is_active:
        raise NotFound("That size isn't available")
    product = await db.get(Product, variant.product_id)
    if product is None or not product.is_active:
        raise NotFound("That product is no longer sold")
    store = await _store_or_online(db, store_id)
    cart = await get_cart(db, user)
    line = next(
        (i for i in cart.items if i.variant_id == variant_id and i.store_id == store.id), None
    )
    wanted = quantity + (line.quantity if line else 0)
    available = await _on_hand(db, variant_id, store.id)
    if wanted > available:
        raise InsufficientStock(
            f"Only {available} left in {variant.size} at {store.city}"
            if available
            else f"{variant.size} is sold out at {store.city}",
            details={"variant_id": variant_id, "store_id": store.id, "available": available},
        )
    if wanted > 10:
        raise AppError("You can add up to 10 of one item")
    if line:
        line.quantity = wanted
    else:
        cart.items.append(
            CartItem(variant_id=variant_id, store_id=store.id, quantity=quantity, source=source)
        )
    await db.flush()


async def update_item(db: AsyncSession, user: User, item_id: int, quantity: int) -> None:
    cart = await get_cart(db, user)
    line = next((i for i in cart.items if i.id == item_id), None)
    if line is None:
        raise NotFound("Item not in your bag")
    available = await _on_hand(db, line.variant_id, line.store_id)
    if quantity > available:
        raise InsufficientStock(f"Only {available} left", details={"available": available})
    line.quantity = quantity
    await db.flush()


async def remove_item(db: AsyncSession, user: User, item_id: int) -> None:
    cart = await get_cart(db, user)
    line = next((i for i in cart.items if i.id == item_id), None)
    if line is None:
        raise NotFound("Item not in your bag")
    cart.items.remove(line)
    await db.flush()


async def cart_view(db: AsyncSession, user: User) -> CartOut:
    cart = await get_cart(db, user)
    if not cart.items:
        return CartOut(items=[], item_count=0, subtotal=0, can_checkout=False)
    variants = {
        v.id: v
        for v in (
            await db.scalars(
                select(ProductVariant).where(
                    ProductVariant.id.in_([i.variant_id for i in cart.items])
                )
            )
        ).all()
    }
    cards = {
        c.id: c for c in await summaries(db, list({v.product_id for v in variants.values()}), None)
    }
    stores = {s.id: s for s in (await db.scalars(select(Store))).all()}
    stock = dict(
        ((v, s), n)
        for v, s, n in (
            await db.execute(
                select(Inventory.variant_id, Inventory.store_id, Inventory.on_hand).where(
                    tuple_(Inventory.variant_id, Inventory.store_id).in_(
                        [(i.variant_id, i.store_id) for i in cart.items]
                    )
                )
            )
        ).all()
    )
    lines = []
    for item in cart.items:
        variant = variants[item.variant_id]
        card = cards.get(variant.product_id)
        if card is None:
            continue
        available = stock.get((item.variant_id, item.store_id), 0)
        issue = None
        if available == 0:
            issue = f"Sold out at {stores[item.store_id].city}"
        elif available < item.quantity:
            issue = f"Only {available} left"
        lines.append(
            CartLine(
                id=item.id,
                product=card,
                variant_id=item.variant_id,
                size=variant.size,
                store_id=item.store_id,
                store_city=stores[item.store_id].city,
                quantity=item.quantity,
                unit_price=card.price,
                line_total=card.price * item.quantity,
                available=available,
                issue=issue,
            )
        )
    return CartOut(
        items=lines,
        item_count=sum(line.quantity for line in lines),
        subtotal=sum(line.line_total for line in lines),
        can_checkout=bool(lines) and not any(line.issue for line in lines),
    )


def _order_number() -> str:
    return f"GB-{datetime.now(UTC):%y%m%d}-{secrets.token_hex(3).upper()}"


async def checkout(db: AsyncSession, user: User) -> Order:
    """Simulated payment: no card details are collected. Caller commits."""
    cart = await get_cart(db, user)
    if not cart.items:
        raise EmptyCart("Your bag is empty")
    keys = sorted({(i.variant_id, i.store_id) for i in cart.items})
    # Lock every affected stock row up front, always in the same order.
    rows = (
        await db.scalars(
            select(Inventory)
            .where(tuple_(Inventory.variant_id, Inventory.store_id).in_(keys))
            .order_by(Inventory.variant_id, Inventory.store_id)
            .with_for_update()
        )
    ).all()
    on_hand = {(r.variant_id, r.store_id): r.on_hand for r in rows}
    short = [
        {
            "variant_id": i.variant_id,
            "store_id": i.store_id,
            "requested": i.quantity,
            "available": on_hand.get((i.variant_id, i.store_id), 0),
        }
        for i in cart.items
        if on_hand.get((i.variant_id, i.store_id), 0) < i.quantity
    ]
    if short:
        raise InsufficientStock(
            "Some items sold out while they were in your bag", details={"items": short}
        )

    variants = {
        v.id: v
        for v in (
            await db.scalars(
                select(ProductVariant).where(ProductVariant.id.in_([k[0] for k in keys]))
            )
        ).all()
    }
    products = {
        p.id: p
        for p in (
            await db.scalars(
                select(Product).where(Product.id.in_({v.product_id for v in variants.values()}))
            )
        )
        .unique()
        .all()
    }
    order = Order(
        id=uuid.uuid4(),
        number=_order_number(),
        user_id=user.id,
        status="placed",
        subtotal=0,
        item_count=0,
    )
    for item in cart.items:
        variant = variants[item.variant_id]
        product = products[variant.product_id]
        await adjust_stock(
            db,
            variant_id=item.variant_id,
            store_id=item.store_id,
            delta=-item.quantity,
            reason="sale",
            reference=order.number,
            actor_user_id=user.id,
        )
        order.items.append(
            OrderItem(
                product_id=product.id,
                variant_id=variant.id,
                store_id=item.store_id,
                quantity=item.quantity,
                unit_price=product.price,
                product_name=product.name,
                size=variant.size,
                colour=product.colour,
            )
        )
        order.subtotal += product.price * item.quantity
        order.item_count += item.quantity
    db.add(order)
    cart.items.clear()
    await db.flush()
    log.info("order_placed", order=order.number, items=order.item_count, subtotal=order.subtotal)
    return order


async def order_view(db: AsyncSession, order: Order) -> OrderOut:
    product_ids = [i.product_id for i in order.items]
    slugs = dict(
        (
            await db.execute(select(Product.id, Product.slug).where(Product.id.in_(product_ids)))
        ).all()
    )
    images = dict(
        (
            await db.execute(
                select(ProductImage.product_id, ProductImage.url).where(
                    ProductImage.product_id.in_(product_ids), ProductImage.position == 0
                )
            )
        ).all()
    )
    cities = dict((await db.execute(select(Store.id, Store.city))).all())
    return OrderOut(
        id=order.id,
        number=order.number,
        status=order.status,
        subtotal=order.subtotal,
        item_count=order.item_count,
        created_at=order.created_at,
        items=[
            OrderLine(
                product_id=i.product_id,
                product_slug=slugs.get(i.product_id),
                image_url=images.get(i.product_id),
                product_name=i.product_name,
                size=i.size,
                colour=i.colour,
                store_city=cities.get(i.store_id, ""),
                quantity=i.quantity,
                unit_price=i.unit_price,
            )
            for i in order.items
        ],
    )


async def list_orders(db: AsyncSession, user: User) -> list[Order]:
    return list(
        (
            await db.scalars(
                select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc())
            )
        ).all()
    )
