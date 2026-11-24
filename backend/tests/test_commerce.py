"""Bag, checkout and personalisation: stock moves exactly once, orders shape the style profile."""

import asyncio

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CustomerStyleProfile, Inventory, InventoryMovement
from app.main import app
from tests.conftest import Catalogue, login, make_user


async def _shopper(
    client: httpx.AsyncClient, session: AsyncSession, email: str = "shop@example.com"
) -> None:
    await make_user(session, email)
    await login(client, email)


async def test_bag_requires_sign_in(client: httpx.AsyncClient, catalogue: Catalogue):
    assert (await client.get("/api/cart")).status_code == 401


async def test_add_respects_live_stock(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    await _shopper(client, session)
    shirt_m = catalogue.variants["navy-linen-shirt:M"]  # 3 in Pune
    r = await client.post(
        "/api/cart/items", json={"variant_id": shirt_m, "store_id": catalogue.pune, "quantity": 2}
    )
    assert r.status_code == 201
    cart = r.json()
    assert cart["item_count"] == 2 and cart["subtotal"] == 2 * 1999 and cart["can_checkout"]

    too_many = await client.post(
        "/api/cart/items", json={"variant_id": shirt_m, "store_id": catalogue.pune, "quantity": 2}
    )
    assert too_many.status_code == 409 and "Only 3 left" in too_many.json()["error"]["message"]

    sold_out = await client.post(
        "/api/cart/items",
        json={"variant_id": catalogue.variants["beige-chinos:M"], "store_id": catalogue.pune},
    )
    assert sold_out.status_code == 409


async def test_checkout_decrements_stock_and_records_the_sale(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    await _shopper(client, session)
    shirt_m = catalogue.variants["navy-linen-shirt:M"]
    sneakers = catalogue.variants["white-sneakers:UK 9"]
    r = await client.post(
        "/api/cart/items/bulk",
        json={
            "items": [
                {"variant_id": shirt_m, "store_id": catalogue.pune, "source": "chat"},
                {"variant_id": sneakers, "store_id": catalogue.pune, "source": "chat"},
            ]
        },
    )
    assert r.json()["item_count"] == 2

    order = await client.post("/api/checkout")
    assert order.status_code == 201, order.text
    body = order.json()
    assert body["number"].startswith("GB-") and body["subtotal"] == 1999 + 3999
    assert {i["product_name"] for i in body["items"]} == {"Linen Shirt", "Leather Sneakers"}

    async def on_hand(variant: int) -> int:
        return await session.scalar(
            select(Inventory.on_hand)
            .where(Inventory.variant_id == variant, Inventory.store_id == catalogue.pune)
            .execution_options(populate_existing=True)
        )

    assert await on_hand(shirt_m) == 2 and await on_hand(sneakers) == 0
    sales = (
        await session.scalars(select(InventoryMovement).where(InventoryMovement.reason == "sale"))
    ).all()
    assert {m.reference for m in sales} == {body["number"]}
    assert (await client.get("/api/cart")).json()["items"] == []
    assert [o["number"] for o in (await client.get("/api/orders")).json()] == [body["number"]]
    assert (await client.post("/api/checkout")).status_code == 400  # empty bag


async def test_two_shoppers_race_for_the_last_pair(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    sneakers = catalogue.variants["white-sneakers:UK 9"]  # exactly 1 in Pune
    clients = []
    for n in range(2):
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
        await make_user(session, f"racer{n}@example.com")
        await login(c, f"racer{n}@example.com")
        assert (
            await c.post(
                "/api/cart/items", json={"variant_id": sneakers, "store_id": catalogue.pune}
            )
        ).status_code == 201
        clients.append(c)
    results = await asyncio.gather(*(c.post("/api/checkout") for c in clients))
    assert sorted(r.status_code for r in results) == [201, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] == "insufficient_stock"
    for c in clients:
        await c.aclose()


async def test_orders_build_a_style_profile_used_in_chat(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    await _shopper(client, session)
    await client.post(
        "/api/cart/items",
        json={"variant_id": catalogue.variants["navy-linen-shirt:M"], "store_id": catalogue.pune},
    )
    await client.post("/api/checkout")
    profile = (await session.scalars(select(CustomerStyleProfile))).one().profile
    assert profile["apparel_size"] == "M" and profile["favourite_colours"] == ["Navy"]
    assert profile["shops_for"] == "men" and catalogue.navy_shirt in profile["recent_product_ids"]

    # A new chat knows the sizes and gender without being told, and says so.
    chat = (await client.post("/api/chat/sessions", json={"store_id": catalogue.pune})).json()
    assert chat["personalized"] is True
    events = []
    async with client.stream(
        "POST", f"/api/chat/sessions/{chat['id']}/messages", json={"text": "office outfit"}
    ) as r:
        async for line in r.aiter_lines():
            if line.startswith("data: "):
                import json

                events.append(json.loads(line[6:]))
    final = events[-1]
    assert final["constraints"]["gender"] == "men" and final["constraints"]["apparel_size"] == "M"
    # It won't re-recommend the shirt they just bought.
    ids = [i["product"]["id"] for g in final["message"]["groups"] for i in g["items"]]
    assert catalogue.navy_shirt not in ids

    # Turning personalisation off for this chat stops it.
    r = await client.patch(
        f"/api/chat/sessions/{chat['id']}", json={"personalization_enabled": False}
    )
    assert r.json()["personalized"] is False


async def test_based_on_what_i_bought_uses_the_profile(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    import json

    from tests.factories import add_product

    await _shopper(client, session)
    await client.post(
        "/api/cart/items",
        json={"variant_id": catalogue.variants["navy-linen-shirt:M"], "store_id": catalogue.pune},
    )
    await client.post("/api/checkout")
    fresh = await add_product(
        session,
        slug="navy-oxford",
        name="Oxford Shirt",
        category="casual-shirts",
        colour="Navy",
        colour_family="blue",
        price=2199,
        stock={catalogue.pune: {"M": 3}},
    )
    chat = (await client.post("/api/chat/sessions", json={"store_id": catalogue.pune})).json()
    events = []
    async with client.stream(
        "POST",
        f"/api/chat/sessions/{chat['id']}/messages",
        json={"text": "Suggest something new based on what I bought before"},
    ) as r:
        async for line in r.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    (group,) = events[-1]["message"]["groups"]
    assert group["title"] == "Picked for you"
    ids = [i["product"]["id"] for i in group["items"]]
    assert fresh.id in ids and catalogue.navy_shirt not in ids  # new, not what they already own
    assert "You often choose navy" in group["items"][ids.index(fresh.id)]["reason"]
