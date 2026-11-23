import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Brand, Product, ProductEmbedding
from app.ml.embeddings import HashingEmbedder
from app.services.embeddings import sync_embeddings
from tests.conftest import Catalogue
from tests.factories import add_product, embed_all


async def _search(client: httpx.AsyncClient, **params) -> dict:
    r = await client.get("/api/search", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(body: dict) -> list[int]:
    return [i["id"] for i in body["items"]]


async def test_search_document_trigger_tracks_product_and_brand(
    session: AsyncSession, catalogue: Catalogue
):
    doc = await session.scalar(
        select(Product.search_document).where(Product.id == catalogue.navy_shirt)
    )
    assert "linen" in doc and "northlin" in doc and "casual" in doc  # name, brand, category
    await session.execute(
        update(Product)
        .where(Product.id == catalogue.navy_shirt)
        .values(name="Seersucker Shirt", description="Seersucker Shirt in navy.")
    )
    await session.commit()
    doc = await session.scalar(
        select(Product.search_document).where(Product.id == catalogue.navy_shirt)
    )
    assert "seersuck" in doc and "linen" not in doc
    assert await session.scalar(select(Brand.name)) == "Northline"


async def test_lexical_mode_without_embeddings(client: httpx.AsyncClient, catalogue: Catalogue):
    body = await _search(client, q="linen shirt")
    assert body["retrieval"]["mode"] == "lexical"
    assert _ids(body)[0] == catalogue.navy_shirt
    assert body["retrieval"]["match"] == "exact"


async def test_hybrid_mode_and_explanations(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    await embed_all(session)
    body = await _search(client, q="linen shirt", explain="true")
    assert body["retrieval"]["mode"] == "hybrid"
    top = body["explain"][0]
    assert top["product_id"] == catalogue.navy_shirt
    assert top["lexical_rank"] == 1 and top["text_rank"] is not None


async def test_parsed_constraints_become_hard_filters(
    client: httpx.AsyncClient, catalogue: Catalogue
):
    body = await _search(client, q="beige chinos under 3000")
    assert _ids(body) == [catalogue.beige_chinos]
    kinds = {i["kind"]: i["label"] for i in body["interpretation"]}
    assert kinds["colour"] == "Beige" and kinds["price"] == "Under ₹3,000"

    # Same words, but the price constraint excludes the only candidate.
    body = await _search(client, q="beige chinos under 2000")
    assert body["items"] == [] and body["retrieval"]["match"] == "none"


async def test_store_stock_is_enforced_before_ranking(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    await embed_all(session)
    # Navy shirt M: 3 in Pune, 0 in Mumbai. Vectors may love it; stock filters still win.
    pune = await _search(client, q="shirt in M", in_stock="true", store_id=catalogue.pune)
    mumbai = await _search(client, q="shirt in M", in_stock="true", store_id=catalogue.mumbai)
    assert catalogue.navy_shirt in _ids(pune)
    assert catalogue.navy_shirt not in _ids(mumbai)
    for item in pune["items"]:
        assert any(s["size"] == "M" and s["in_stock"] for s in item["sizes"])


async def test_inactive_products_never_surface(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    await embed_all(session)
    body = await _search(client, q="old black tee")
    assert catalogue.retired_tee not in _ids(body)


async def test_no_literal_match_is_reported_as_related(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    await embed_all(session)
    body = await _search(client, q="velvet tuxedo")
    assert body["retrieval"]["match"] in {"related", "none"}
    assert body["retrieval"]["lexical_candidates"] >= 0


async def test_explicit_filters_beat_parsed_ones_and_sort_applies(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    await add_product(
        session,
        slug="stone-chinos",
        name="Relaxed Chinos",
        category="chinos",
        colour="Stone",
        price=1799,
        stock={catalogue.pune: {"M": 2}},
    )
    body = await _search(client, q="chinos", sort="price_asc")
    assert [i["price"] for i in body["items"]] == [1799, 2499]
    # Parsed "beige" would narrow to one; an explicit colour param wins.
    body = await _search(client, q="beige chinos", colour="stone")
    assert [i["colour"] for i in body["items"]] == ["Stone"]


async def test_products_endpoint_delegates_free_text(
    client: httpx.AsyncClient, catalogue: Catalogue
):
    r = await client.get("/api/products", params={"q": "sneakers"})
    assert [i["id"] for i in r.json()["items"]] == [catalogue.white_sneakers]


async def test_embedding_sync_is_incremental(session: AsyncSession, catalogue: Catalogue):
    embedder = HashingEmbedder()
    first = await sync_embeddings(session, embedder)
    assert first.embedded == first.checked == 4  # inactive products keep vectors too
    assert (await sync_embeddings(session, embedder)).embedded == 0

    await session.execute(
        update(Product).where(Product.id == catalogue.navy_shirt).values(colour="Olive")
    )
    await session.commit()
    changed = await sync_embeddings(session, embedder)
    assert changed.embedded == 1
    assert (await sync_embeddings(session, embedder, force=True)).embedded == 4
    row = await session.get(ProductEmbedding, catalogue.navy_shirt)
    assert row.model_name == "hashing-v1" and len(row.text_embedding) == 512
