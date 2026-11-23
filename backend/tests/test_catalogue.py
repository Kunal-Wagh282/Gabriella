import httpx

from tests.conftest import Catalogue


async def _ids(client: httpx.AsyncClient, **params) -> set[int]:
    r = await client.get("/api/products", params=params)
    assert r.status_code == 200, r.text
    return {item["id"] for item in r.json()["items"]}


async def test_lists_only_active_products(client: httpx.AsyncClient, catalogue: Catalogue):
    ids = await _ids(client)
    assert catalogue.retired_tee not in ids
    assert ids == {catalogue.navy_shirt, catalogue.beige_chinos, catalogue.white_sneakers}


async def test_parent_category_includes_children(client: httpx.AsyncClient, catalogue: Catalogue):
    assert await _ids(client, category="tops") == {catalogue.navy_shirt}
    assert await _ids(client, category=["chinos", "sneakers"]) == {
        catalogue.beige_chinos,
        catalogue.white_sneakers,
    }


async def test_price_colour_and_gender_filters(client: httpx.AsyncClient, catalogue: Catalogue):
    assert await _ids(client, max_price=2500) == {catalogue.navy_shirt, catalogue.beige_chinos}
    assert await _ids(client, min_price=3000) == {catalogue.white_sneakers}
    # Colour matches either the exact colour name or its family.
    assert await _ids(client, colour="navy") == {catalogue.navy_shirt}
    assert await _ids(client, colour="blue") == {catalogue.navy_shirt}
    assert await _ids(client, gender="unisex") == {catalogue.white_sneakers}
    assert await _ids(client, on_sale="true") == {catalogue.beige_chinos}


async def test_size_and_store_stock_must_match_the_same_variant(
    client: httpx.AsyncClient, catalogue: Catalogue
):
    # Beige chinos: M is sold out in Pune but stocked in Mumbai.
    pune_m = await _ids(client, size="M", in_stock="true", store_id=catalogue.pune)
    assert pune_m == {catalogue.navy_shirt}
    mumbai_m = await _ids(client, size="M", in_stock="true", store_id=catalogue.mumbai)
    assert mumbai_m == {catalogue.beige_chinos}
    anywhere_m = await _ids(client, size="M", in_stock="true")
    assert anywhere_m == {catalogue.navy_shirt, catalogue.beige_chinos}


async def test_summary_reports_per_size_availability(
    client: httpx.AsyncClient, catalogue: Catalogue
):
    r = await client.get("/api/products", params={"category": "chinos", "store_id": catalogue.pune})
    (item,) = r.json()["items"]
    assert {s["size"]: s["in_stock"] for s in item["sizes"]} == {"M": False, "L": True}
    assert item["in_stock"] is True
    assert item["image"]["url"].endswith("beige-chinos.webp")


async def test_keyword_search(client: httpx.AsyncClient, catalogue: Catalogue):
    assert await _ids(client, q="linen") == {catalogue.navy_shirt}
    assert await _ids(client, q="northline sneakers") == {catalogue.white_sneakers}
    assert await _ids(client, q="velvet tuxedo") == set()


async def test_sorting_and_pagination(client: httpx.AsyncClient, catalogue: Catalogue):
    r = await client.get("/api/products", params={"sort": "price_asc", "page_size": 2})
    body = r.json()
    assert body["total"] == 3
    assert [i["price"] for i in body["items"]] == [1999, 2499]
    page2 = (
        await client.get("/api/products", params={"sort": "price_asc", "page_size": 2, "page": 2})
    ).json()
    assert [i["price"] for i in page2["items"]] == [3999]
    featured = (await client.get("/api/products")).json()["items"]
    assert featured[0]["id"] == catalogue.beige_chinos  # highest popularity


async def test_product_detail_with_store_stock(client: httpx.AsyncClient, catalogue: Catalogue):
    r = await client.get("/api/products/beige-chinos", params={"store_id": catalogue.pune})
    assert r.status_code == 200
    detail = r.json()
    assert detail["parent_category"]["slug"] == "bottoms"
    sizes = {v["size"]: v for v in detail["variants"]}
    assert sizes["M"]["available_at_selected_store"] == 0
    assert sizes["L"]["available_at_selected_store"] == 5
    assert {s["store_code"]: s["on_hand"] for s in sizes["M"]["stock"]} == {"PUN": 0, "BOM": 4}

    by_id = await client.get(f"/api/products/{catalogue.beige_chinos}")
    assert by_id.json()["slug"] == "beige-chinos"
    assert (await client.get("/api/products/nope")).status_code == 404


async def test_facets(client: httpx.AsyncClient, catalogue: Catalogue):
    facets = (await client.get("/api/catalogue/facets")).json()
    tops = next(c for c in facets["categories"] if c["slug"] == "tops")
    assert tops["product_count"] == 1  # the retired tee isn't counted
    assert {c["name"] for c in facets["colours"]} == {"Navy", "Beige", "White"}
    assert facets["price_min"] == 1999 and facets["price_max"] == 3999


async def test_stores_and_validation(client: httpx.AsyncClient, catalogue: Catalogue):
    stores = (await client.get("/api/stores")).json()
    assert {s["code"] for s in stores} == {"PUN", "BOM"}
    bad = await client.get("/api/products", params={"sort": "random"})
    assert bad.status_code == 422
