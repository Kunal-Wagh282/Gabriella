"""Seed the database with the simulated catalogue, stores, stock and demo accounts.

uv run python -m seed               # seed an empty database
uv run python -m seed --if-empty    # no-op when products already exist (used by Docker)
uv run python -m seed --reset       # wipe catalogue/stock/users first (asks for confirmation)
"""

import argparse
import asyncio
import sys
import time

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import (
    Brand,
    Category,
    Inventory,
    InventoryMovement,
    Product,
    ProductImage,
    ProductVariant,
    Store,
    User,
    UserPreferences,
)
from app.db.session import SessionLocal, engine
from seed.generator import GenProduct, generate_catalogue
from seed.history import ensure_demo_history
from seed.images import render_images
from seed.taxonomy import BRANDS, GROUPS, SPECS, STORES

RESET_TABLES = [
    "inventory_movements",
    "inventory",
    "product_embeddings",
    "product_images",
    "product_variants",
    "products",
    "categories",
    "brands",
    "auth_sessions",
    "user_preferences",
    "users",
    "stores",
]


async def _insert_reference_data(
    session: AsyncSession,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    store_rows = await session.execute(
        insert(Store).returning(Store.code, Store.id),
        [
            {
                "code": s.code,
                "name": s.name,
                "city": s.city,
                "address": s.address,
                "is_online": s.is_online,
            }
            for s in STORES
        ],
    )
    stores = dict(store_rows.all())

    brand_rows = await session.execute(
        insert(Brand).returning(Brand.slug, Brand.id),
        [
            {"slug": b.slug, "name": b.name, "tagline": b.tagline, "price_tier": b.tier}
            for b in BRANDS
        ],
    )
    brands = dict(brand_rows.all())

    group_rows = await session.execute(
        insert(Category).returning(Category.slug, Category.id),
        [{"slug": slug, "name": name, "position": i} for i, (slug, name) in enumerate(GROUPS)],
    )
    groups = dict(group_rows.all())
    leaf_rows = await session.execute(
        insert(Category).returning(Category.slug, Category.id),
        [
            {
                "slug": s.slug,
                "name": s.name,
                "parent_id": groups[s.group],
                "slot": s.slot,
                "position": i,
            }
            for i, s in enumerate(SPECS)
        ],
    )
    return stores, brands, dict(leaf_rows.all())


async def _insert_products(
    session: AsyncSession,
    products: list[GenProduct],
    stores: dict[str, int],
    brands: dict[str, int],
    categories: dict[str, int],
    media_url: str,
) -> None:
    rows = await session.execute(
        insert(Product).returning(Product.slug, Product.id),
        [
            {
                "style_code": p.style_code,
                "slug": p.slug,
                "name": p.name,
                "brand_id": brands[p.brand_slug],
                "category_id": categories[p.category_slug],
                "gender": p.gender,
                "colour": p.colour,
                "colour_hex": p.colour_hex,
                "colour_family": p.colour_family,
                "secondary_colours": p.secondary_colours,
                "pattern": p.pattern,
                "material": p.material,
                "fit": p.fit,
                "style_tags": p.style_tags,
                "occasions": p.occasions,
                "seasons": p.seasons,
                "formality": p.formality,
                "price": p.price,
                "mrp": p.mrp,
                "description": p.description,
                "popularity": p.popularity,
                "is_active": p.is_active,
                "created_at": p.created_at,
                "updated_at": p.created_at,
            }
            for p in products
        ],
    )
    product_ids = dict(rows.all())

    await session.execute(
        insert(ProductImage),
        [
            row
            for p in products
            for row in (
                {
                    "product_id": product_ids[p.slug],
                    "url": f"{media_url}/products/{p.slug}.webp",
                    "alt": f"{p.name} in {p.colour.lower()}, flat-lay",
                    "kind": "flatlay",
                    "position": 0,
                },
                {
                    "product_id": product_ids[p.slug],
                    "url": f"{media_url}/products/{p.slug}-swatch.webp",
                    "alt": f"{p.colour} {p.material.lower()} fabric close-up",
                    "kind": "swatch",
                    "position": 1,
                },
            )
        ],
    )

    variant_rows = await session.execute(
        insert(ProductVariant).returning(ProductVariant.sku, ProductVariant.id),
        [
            {
                "product_id": product_ids[p.slug],
                "sku": v.sku,
                "size": v.size,
                "size_rank": v.size_rank,
            }
            for p in products
            for v in p.variants
        ],
    )
    variant_ids = dict(variant_rows.all())

    stock_rows = [
        {"variant_id": variant_ids[v.sku], "store_id": stores[code], "on_hand": qty}
        for p in products
        for v in p.variants
        for code, qty in v.stock.items()
    ]
    for chunk in range(0, len(stock_rows), 5000):
        batch = stock_rows[chunk : chunk + 5000]
        await session.execute(insert(Inventory), batch)
        await session.execute(
            insert(InventoryMovement),
            [
                {**r, "delta": r["on_hand"], "on_hand_after": r["on_hand"], "reason": "seed"}
                for r in batch
                if r["on_hand"] > 0
            ],
        )


async def _insert_users(session: AsyncSession, stores: dict[str, int]) -> None:
    settings = get_settings()
    accounts = [
        (
            settings.seed_admin_email,
            settings.seed_admin_password.get_secret_value(),
            "Gabriella Admin",
            True,
            "WEB",
        ),
        (
            settings.seed_demo_email,
            settings.seed_demo_password.get_secret_value(),
            "Asha Demo",
            False,
            "PUN",
        ),
    ]
    for email, password, name, is_admin, store_code in accounts:
        user = User(
            email=email.lower(),
            password_hash=hash_password(password),
            full_name=name,
            is_admin=is_admin,
        )
        user.preferences = UserPreferences(
            preferred_store_id=stores[store_code], personalization_enabled=True
        )
        session.add(user)


async def _demo_history() -> None:
    async with SessionLocal() as session, session.begin():
        orders = await ensure_demo_history(session)
    if orders:
        print(f"seed: demo shopper purchase history, {orders} past orders")


async def seed(*, if_empty: bool, reset: bool, skip_images: bool, workers: int) -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        if reset:
            await session.execute(
                text(f"TRUNCATE {', '.join(RESET_TABLES)} RESTART IDENTITY CASCADE")
            )
            await session.commit()
            print("reset: catalogue, stock and user tables truncated")
        existing = await session.scalar(select(func.count()).select_from(Product))

    products = generate_catalogue()
    if not skip_images:
        # Renders are deterministic, so a fresh media volume heals itself even when data exists.
        render_images(products, settings.media_root, workers)

    if existing:
        if if_empty:
            print(f"seed: {existing} products already present, skipping data")
            await _demo_history()
            await engine.dispose()
            return
        sys.exit("seed: database already has products; use --reset to rebuild it")

    start = time.perf_counter()
    async with SessionLocal() as session, session.begin():
        stores, brands, categories = await _insert_reference_data(session)
        await _insert_products(session, products, stores, brands, categories, settings.media_url)
        await _insert_users(session, stores)
    await _demo_history()
    variants = sum(len(p.variants) for p in products)
    print(
        f"seed: {len(products)} products, {variants} variants, {variants * len(STORES)} stock rows, "
        f"{len(STORES)} stores, {len(BRANDS)} brands in {time.perf_counter() - start:.1f}s"
    )
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--if-empty", action="store_true", help="skip when products already exist")
    parser.add_argument(
        "--reset", action="store_true", help="truncate catalogue, stock and user tables first"
    )
    parser.add_argument("--yes", action="store_true", help="don't prompt before --reset")
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.reset and not args.yes:
        answer = input(
            "This deletes all products, stock, orders and users. Type 'reset' to continue: "
        )
        if answer.strip() != "reset":
            sys.exit("aborted")
    asyncio.run(
        seed(
            if_empty=args.if_empty,
            reset=args.reset,
            skip_images=args.skip_images,
            workers=args.workers,
        )
    )


if __name__ == "__main__":
    main()
