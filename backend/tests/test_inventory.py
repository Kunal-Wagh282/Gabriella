import asyncio

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InsufficientStock
from app.db.models import Inventory, InventoryMovement
from app.db.session import SessionLocal
from app.services.inventory import adjust_stock
from tests.conftest import Catalogue, login, make_user


async def test_database_rejects_negative_stock(session: AsyncSession, catalogue: Catalogue):
    row = await session.get(Inventory, (catalogue.variants["white-sneakers:UK 9"], catalogue.pune))
    row.on_hand = -1
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_concurrent_decrements_never_oversell(catalogue: Catalogue):
    """Ten buyers race for the last unit; row locking lets exactly one through."""
    variant = catalogue.variants["white-sneakers:UK 9"]  # 1 unit in Pune

    async def buy() -> bool:
        async with SessionLocal() as s, s.begin():
            try:
                await adjust_stock(
                    s, variant_id=variant, store_id=catalogue.pune, delta=-1, reason="sale"
                )
                return True
            except InsufficientStock:
                return False

    results = await asyncio.gather(*(buy() for _ in range(10)))
    assert results.count(True) == 1

    async with SessionLocal() as s:
        assert (await s.get(Inventory, (variant, catalogue.pune))).on_hand == 0
        sales = (
            await s.scalars(select(InventoryMovement).where(InventoryMovement.reason == "sale"))
        ).all()
        assert len(sales) == 1 and sales[0].on_hand_after == 0


async def test_admin_restock_endpoint(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    variant = catalogue.variants["beige-chinos:M"]
    await make_user(session, "shopper@example.com")
    await login(client, "shopper@example.com")
    payload = {"variant_id": variant, "store_id": catalogue.pune, "delta": 6}
    assert (await client.post("/api/admin/inventory/adjust", json=payload)).status_code == 403

    await make_user(session, "admin@example.com", is_admin=True)
    await login(client, "admin@example.com")
    r = await client.post("/api/admin/inventory/adjust", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["on_hand"] == 6

    r = await client.post(
        "/api/admin/inventory/adjust",
        json={
            "variant_id": variant,
            "store_id": catalogue.pune,
            "set_to": 2,
            "reason": "adjustment",
        },
    )
    assert r.json()["on_hand"] == 2

    too_many = await client.post(
        "/api/admin/inventory/adjust",
        json={"variant_id": variant, "store_id": catalogue.pune, "delta": -5},
    )
    assert too_many.status_code == 409
    assert too_many.json()["error"]["code"] == "insufficient_stock"

    neither = await client.post(
        "/api/admin/inventory/adjust", json={"variant_id": variant, "store_id": catalogue.pune}
    )
    assert neither.status_code == 422

    # The restocked size now shows as available in Pune.
    listing = await client.get(
        "/api/products",
        params={"size": "M", "in_stock": "true", "store_id": catalogue.pune, "category": "chinos"},
    )
    assert listing.json()["total"] == 1

    stock = await client.get(f"/api/admin/inventory/{variant}")
    assert {s["store_code"]: s["on_hand"] for s in stock.json()} == {"PUN": 2, "BOM": 4}
