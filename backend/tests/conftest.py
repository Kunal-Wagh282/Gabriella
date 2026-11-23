"""Test fixtures.

Runs against the `gabriella_test` database (TEST_DATABASE_URL). The schema is built with
the real Alembic migrations once per session, and every test starts from empty tables.
"""

import asyncio
import os

os.environ["GABRIELLA_ENV"] = "test"
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
# Deterministic, model-free vectors; CLIP is exercised by the eval suite instead.
os.environ["EMBEDDING_BACKEND"] = "hashing"
# Never call a real model from tests, even if a developer .env holds an API key.
os.environ["LLM_PROVIDER"] = "none"

from collections.abc import AsyncIterator  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.models import (  # noqa: E402
    Brand,
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
    Store,
    User,
    UserPreferences,
)
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
TABLES = [
    "agent_traces",
    "chat_messages",
    "chat_sessions",
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


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().test_database_url)
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session", autouse=True)
async def migrated_database() -> None:
    cfg = _alembic_config()
    # Down then up: exercises both directions of every migration.
    await asyncio.to_thread(command.downgrade, cfg, "base")
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest.fixture(autouse=True)
async def clean_tables(migrated_database: None) -> None:
    async with SessionLocal() as session:
        await session.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
        await session.commit()


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@dataclass
class Catalogue:
    pune: int
    mumbai: int
    navy_shirt: int
    beige_chinos: int
    white_sneakers: int
    retired_tee: int
    variants: dict[str, int]  # "<product>:<size>" -> variant id


@pytest.fixture
async def catalogue(session: AsyncSession) -> Catalogue:
    """A tiny, hand-built catalogue with known stock levels."""
    pune = Store(code="PUN", name="Pune", city="Pune", address="KP")
    mumbai = Store(code="BOM", name="Mumbai", city="Mumbai", address="Bandra")
    brand = Brand(slug="northline", name="Northline", tagline="", price_tier="mid")
    tops = Category(slug="tops", name="Tops", position=0)
    bottoms = Category(slug="bottoms", name="Bottoms", position=1)
    footwear = Category(slug="footwear", name="Footwear", position=2)
    session.add_all([pune, mumbai, brand, tops, bottoms, footwear])
    await session.flush()
    shirts = Category(slug="casual-shirts", name="Casual Shirts", parent_id=tops.id, slot="top")
    tees = Category(slug="t-shirts", name="T-Shirts", parent_id=tops.id, slot="top")
    chinos = Category(slug="chinos", name="Chinos", parent_id=bottoms.id, slot="bottom")
    sneakers = Category(slug="sneakers", name="Sneakers", parent_id=footwear.id, slot="footwear")
    session.add_all([shirts, tees, chinos, sneakers])
    await session.flush()

    def product(slug: str, name: str, cat: Category, colour: str, price: int, **kw) -> Product:
        defaults = dict(
            style_code=slug.upper()[:8],
            gender="men",
            colour_hex="#123456",
            colour_family=kw.pop("family", "neutral"),
            pattern="solid",
            material="Cotton",
            fit="Regular",
            style_tags=["casual"],
            occasions=["casual"],
            seasons=["all-season"],
            formality=2,
            mrp=price,
            description=f"{name} in {colour}.",
        )
        return Product(
            slug=slug,
            name=name,
            brand_id=brand.id,
            category_id=cat.id,
            colour=colour,
            price=price,
            **{**defaults, **kw},
        )

    navy_shirt = product(
        "navy-linen-shirt",
        "Linen Shirt",
        shirts,
        "Navy",
        1999,
        family="blue",
        style_tags=["smart-casual"],
        occasions=["dinner", "office"],
        popularity=50,
    )
    beige_chinos = product(
        "beige-chinos", "Slim Chinos", chinos, "Beige", 2499, mrp=2999, popularity=80
    )
    white_sneakers = product(
        "white-sneakers",
        "Leather Sneakers",
        sneakers,
        "White",
        3999,
        gender="unisex",
        family="white",
        popularity=10,
    )
    retired_tee = product("retired-tee", "Old Tee", tees, "Black", 599, is_active=False)
    session.add_all([navy_shirt, beige_chinos, white_sneakers, retired_tee])
    await session.flush()
    for p in (navy_shirt, beige_chinos, white_sneakers, retired_tee):
        session.add(
            ProductImage(
                product_id=p.id,
                url=f"/media/products/{p.slug}.webp",
                alt=p.name,
                kind="flatlay",
                position=0,
            )
        )

    # (product, size, pune stock, mumbai stock)
    plan = [
        (navy_shirt, "M", 3, 0),
        (navy_shirt, "L", 0, 2),
        (beige_chinos, "M", 0, 4),
        (beige_chinos, "L", 5, 5),
        (white_sneakers, "UK 9", 1, 0),
        (retired_tee, "M", 9, 9),
    ]
    variants: dict[str, int] = {}
    for rank, (p, size, pun_qty, bom_qty) in enumerate(plan):
        v = ProductVariant(
            product_id=p.id, sku=f"{p.slug}-{size}".upper(), size=size, size_rank=rank
        )
        session.add(v)
        await session.flush()
        variants[f"{p.slug}:{size}"] = v.id
        session.add_all(
            [
                Inventory(variant_id=v.id, store_id=pune.id, on_hand=pun_qty),
                Inventory(variant_id=v.id, store_id=mumbai.id, on_hand=bom_qty),
            ]
        )
    await session.commit()
    return Catalogue(
        pune.id,
        mumbai.id,
        navy_shirt.id,
        beige_chinos.id,
        white_sneakers.id,
        retired_tee.id,
        variants,
    )


async def make_user(
    session: AsyncSession, email: str, password: str = "correct-horse", *, is_admin: bool = False
) -> User:
    user = User(
        email=email, password_hash=hash_password(password), full_name="Test User", is_admin=is_admin
    )
    user.preferences = UserPreferences(personalization_enabled=True)
    session.add(user)
    await session.commit()
    return user


async def login(client: httpx.AsyncClient, email: str, password: str = "correct-horse") -> None:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
