import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import Catalogue
from tests.factories import add_product, embed_all


async def _alternatives(session: AsyncSession, catalogue: Catalogue) -> dict[str, int]:
    """Two chinos and a pair of trousers around the fixture's beige chinos."""
    stone = await add_product(
        session,
        slug="stone-chinos",
        name="Relaxed Chinos",
        category="chinos",
        colour="Stone",
        price=2299,
        stock={catalogue.pune: {"M": 2, "L": 1}, catalogue.mumbai: {"M": 0}},
    )
    khaki = await add_product(
        session,
        slug="khaki-chinos",
        name="Tapered Chinos",
        category="chinos",
        colour="Khaki",
        colour_family="green",
        price=2199,
        stock={catalogue.pune: {"M": 0}, catalogue.mumbai: {"M": 5}},
    )
    womens = await add_product(
        session,
        slug="womens-chinos",
        name="Wide Chinos",
        category="chinos",
        colour="Beige",
        gender="women",
        price=2399,
        stock={catalogue.pune: {"M": 4}},
    )
    return {"stone": stone.id, "khaki": khaki.id, "womens": womens.id}


async def _similar(client: httpx.AsyncClient, key: str | int, **params) -> list[dict]:
    r = await client.get(f"/api/products/{key}/similar", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_similar_stays_in_slot_and_gender(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    alt = await _alternatives(session, catalogue)
    await embed_all(session)
    results = await _similar(client, "beige-chinos")
    ids = [r["product"]["id"] for r in results]
    assert catalogue.beige_chinos not in ids  # never itself
    assert catalogue.navy_shirt not in ids and catalogue.white_sneakers not in ids  # other slots
    assert alt["womens"] not in ids  # men's seed: men's or unisex only
    assert set(ids) == {alt["stone"], alt["khaki"]}
    assert all(0 <= r["similarity"] <= 1 for r in results)
    assert any("Also chinos" in r["reasons"] for r in results)


async def test_similar_in_my_size_at_my_store(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    """ "Something like these beige chinos, in M, at Pune": only the stone pair qualifies."""
    alt = await _alternatives(session, catalogue)
    await embed_all(session)
    results = await _similar(
        client, catalogue.beige_chinos, size="M", in_stock="true", store_id=catalogue.pune
    )
    assert [r["product"]["id"] for r in results] == [alt["stone"]]
    sizes = {s["size"]: s["in_stock"] for s in results[0]["product"]["sizes"]}
    assert sizes["M"] is True

    mumbai = await _similar(
        client, catalogue.beige_chinos, size="M", in_stock="true", store_id=catalogue.mumbai
    )
    assert [r["product"]["id"] for r in mumbai] == [alt["khaki"]]


async def test_similar_falls_back_without_embeddings(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    alt = await _alternatives(session, catalogue)
    results = await _similar(client, "beige-chinos", limit=1)
    # Same category + same colour family ranks first on attributes alone.
    assert [r["product"]["id"] for r in results] == [alt["stone"]]


async def test_similar_unknown_product(client: httpx.AsyncClient, catalogue: Catalogue):
    assert (await client.get("/api/products/nope/similar")).status_code == 404


async def test_variant_availability(client: httpx.AsyncClient, catalogue: Catalogue):
    variant = catalogue.variants["beige-chinos:M"]
    r = await client.get(
        f"/api/variants/{variant}/availability", params={"store_id": catalogue.pune}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["in_stock_at_store"] is False and body["on_hand_at_store"] == 0
    assert {s["store_code"]: s["on_hand"] for s in body["stores"]} == {"PUN": 0, "BOM": 4}

    anywhere = (await client.get(f"/api/variants/{variant}/availability")).json()
    assert anywhere["in_stock_at_store"] is None
    assert (await client.get("/api/variants/999999/availability")).status_code == 404
