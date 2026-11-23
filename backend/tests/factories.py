"""Helpers for adding products on top of the `catalogue` fixture."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Brand, Category, Inventory, Product, ProductImage, ProductVariant
from app.ml.embeddings import HashingEmbedder
from app.services.embeddings import sync_embeddings


async def add_product(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
    category: str,
    colour: str,
    price: int,
    stock: dict[int, dict[str, int]],
    **attrs,
) -> Product:
    """`stock` maps store_id -> {size: on_hand}."""
    brand_id = await session.scalar(select(Brand.id).limit(1))
    category_id = await session.scalar(select(Category.id).where(Category.slug == category))
    defaults = dict(
        style_code=slug.upper()[:10],
        gender="men",
        colour_hex="#777777",
        colour_family="neutral",
        pattern="solid",
        material="Cotton",
        fit="Regular",
        style_tags=["casual"],
        occasions=["casual"],
        seasons=["all-season"],
        formality=2,
        mrp=price,
        description=f"{name} in {colour.lower()}.",
    )
    product = Product(
        slug=slug,
        name=name,
        brand_id=brand_id,
        category_id=category_id,
        colour=colour,
        price=price,
        **{**defaults, **attrs},
    )
    session.add(product)
    await session.flush()
    session.add(
        ProductImage(
            product_id=product.id,
            url=f"/media/products/{slug}.webp",
            alt=name,
            kind="flatlay",
            position=0,
        )
    )
    sizes = sorted({size for by_size in stock.values() for size in by_size})
    for rank, size in enumerate(sizes):
        variant = ProductVariant(
            product_id=product.id, sku=f"{slug}-{size}".upper(), size=size, size_rank=rank
        )
        session.add(variant)
        await session.flush()
        for store_id, by_size in stock.items():
            session.add(
                Inventory(variant_id=variant.id, store_id=store_id, on_hand=by_size.get(size, 0))
            )
    await session.commit()
    return product


async def embed_all(session: AsyncSession) -> None:
    await sync_embeddings(session, HashingEmbedder())
