import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import NotFound
from app.db.models import Order
from app.schemas.commerce import CartAdd, CartAddMany, CartOut, CartUpdate, OrderOut
from app.services import commerce
from app.services.profile import rebuild_profile

router = APIRouter(tags=["commerce"])


@router.get("/cart", response_model=CartOut)
async def get_cart(user: CurrentUser, db: SessionDep):
    view = await commerce.cart_view(db, user)
    await db.commit()
    return view


@router.post("/cart/items", response_model=CartOut, status_code=status.HTTP_201_CREATED)
async def add_to_cart(body: CartAdd, user: CurrentUser, db: SessionDep):
    """Add one size from one store. Fails with 409 `insufficient_stock` if it can't be bought."""
    await commerce.add_item(
        db,
        user,
        variant_id=body.variant_id,
        store_id=body.store_id,
        quantity=body.quantity,
        source=body.source,
    )
    await db.commit()
    return await commerce.cart_view(db, user)


@router.post("/cart/items/bulk", response_model=CartOut, status_code=status.HTTP_201_CREATED)
async def add_outfit_to_cart(body: CartAddMany, user: CurrentUser, db: SessionDep):
    """Add a whole look in one go: all pieces or none."""
    for item in body.items:
        await commerce.add_item(
            db,
            user,
            variant_id=item.variant_id,
            store_id=item.store_id,
            quantity=item.quantity,
            source=item.source,
        )
    await db.commit()
    return await commerce.cart_view(db, user)


@router.patch("/cart/items/{item_id}", response_model=CartOut)
async def update_cart_item(item_id: int, body: CartUpdate, user: CurrentUser, db: SessionDep):
    await commerce.update_item(db, user, item_id, body.quantity)
    await db.commit()
    return await commerce.cart_view(db, user)


@router.delete("/cart/items/{item_id}", response_model=CartOut)
async def remove_cart_item(item_id: int, user: CurrentUser, db: SessionDep):
    await commerce.remove_item(db, user, item_id)
    await db.commit()
    return await commerce.cart_view(db, user)


@router.post("/checkout", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def checkout(user: CurrentUser, db: SessionDep):
    """Simulated checkout: locks and decrements stock, creates the order. No payment is taken."""
    order = await commerce.checkout(db, user)
    await db.commit()
    await rebuild_profile(db, user.id)  # personalisation reflects the purchase straight away
    await db.commit()
    return await commerce.order_view(db, order)


@router.get("/orders", response_model=list[OrderOut])
async def list_orders(user: CurrentUser, db: SessionDep):
    return [await commerce.order_view(db, o) for o in await commerce.list_orders(db, user)]


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: uuid.UUID, user: CurrentUser, db: SessionDep):
    order = await db.get(Order, order_id)
    if order is None or order.user_id != user.id:
        raise NotFound("Order not found")
    return await commerce.order_view(db, order)
