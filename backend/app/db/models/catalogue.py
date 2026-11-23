from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.db.base import Base, TimestampMixin

EMBEDDING_DIM = 512  # CLIP ViT-B/32: text and image vectors share this space

GENDERS = ("men", "women", "unisex")
# Outfit slot a category fills. Grouping categories (e.g. "Tops") have no slot.
SLOTS = ("top", "bottom", "onepiece", "outerwear", "footwear", "accessory")


class Brand(TimestampMixin, Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    tagline: Mapped[str] = mapped_column(String(255), default="")
    price_tier: Mapped[str] = mapped_column(String(16))  # value | mid | premium

    __table_args__ = (
        CheckConstraint("price_tier IN ('value','mid','premium')", name="price_tier"),
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    slot: Mapped[str | None] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(SmallInteger, default=0)

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id")

    __table_args__ = (CheckConstraint(f"slot IS NULL OR slot IN {SLOTS}", name="slot"),)


class Product(TimestampMixin, Base):
    """One colourway of a style. Sizes live on `ProductVariant`."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    style_code: Mapped[str] = mapped_column(String(32), index=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    gender: Mapped[str] = mapped_column(String(8))

    colour: Mapped[str] = mapped_column(String(40))
    colour_hex: Mapped[str] = mapped_column(String(7))
    colour_family: Mapped[str] = mapped_column(String(20), index=True)
    secondary_colours: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    pattern: Mapped[str] = mapped_column(String(24))
    material: Mapped[str] = mapped_column(String(60))
    fit: Mapped[str] = mapped_column(String(24))

    style_tags: Mapped[list[str]] = mapped_column(ARRAY(String(24)), default=list)
    occasions: Mapped[list[str]] = mapped_column(ARRAY(String(24)), default=list)
    seasons: Mapped[list[str]] = mapped_column(ARRAY(String(16)), default=list)
    formality: Mapped[int] = mapped_column(SmallInteger)  # 1 = loungewear … 5 = black tie

    price: Mapped[int] = mapped_column(Integer)  # whole rupees (INR)
    mrp: Mapped[int] = mapped_column(Integer)  # list price; > price means on sale
    description: Mapped[str] = mapped_column(Text)
    popularity: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Weighted full-text document, maintained by the `products_search_document` trigger.
    search_document: Mapped[str | None] = deferred(mapped_column(TSVECTOR))

    brand: Mapped[Brand] = relationship(lazy="joined")
    category: Mapped[Category] = relationship(lazy="joined")
    images: Mapped[list["ProductImage"]] = relationship(
        order_by="ProductImage.position", cascade="all, delete-orphan"
    )
    variants: Mapped[list["ProductVariant"]] = relationship(
        order_by="ProductVariant.size_rank", back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(f"gender IN {GENDERS}", name="gender"),
        CheckConstraint("formality BETWEEN 1 AND 5", name="formality"),
        CheckConstraint("price > 0 AND mrp >= price", name="price"),
        Index("ix_products_active_price", "is_active", "price"),
        Index("ix_products_style_tags", "style_tags", postgresql_using="gin"),
        Index("ix_products_occasions", "occasions", postgresql_using="gin"),
        Index("ix_products_search_document", "search_document", postgresql_using="gin"),
    )


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(255))
    alt: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16), default="flatlay")  # flatlay | swatch
    position: Mapped[int] = mapped_column(SmallInteger, default=0)


class ProductVariant(TimestampMixin, Base):
    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    sku: Mapped[str] = mapped_column(String(48), unique=True)
    size: Mapped[str] = mapped_column(String(16))
    size_rank: Mapped[int] = mapped_column(SmallInteger)  # display order (XS < S < M …)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    product: Mapped[Product] = relationship(back_populates="variants")

    __table_args__ = (Index("uq_product_variants_product_size", "product_id", "size", unique=True),)


class ProductEmbedding(Base):
    """Search-only vectors. Never consulted for price or stock."""

    __tablename__ = "product_embeddings"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    text_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    image_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    model_name: Mapped[str] = mapped_column(String(80))
    content_hash: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "ix_product_embeddings_text_hnsw",
            "text_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"text_embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_product_embeddings_image_hnsw",
            "image_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"image_embedding": "vector_cosine_ops"},
        ),
    )
