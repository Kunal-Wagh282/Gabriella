import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Cart(TimestampMixin, Base):
    """One open bag per signed-in shopper."""

    __tablename__ = "carts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    items: Mapped[list["CartItem"]] = relationship(
        order_by="CartItem.id", cascade="all, delete-orphan", lazy="selectin"
    )


class CartItem(Base):
    """A size from a specific store. Stock is checked live; nothing is held until checkout."""

    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), index=True
    )
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id", ondelete="CASCADE"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    quantity: Mapped[int] = mapped_column(SmallInteger, default=1)
    source: Mapped[str] = mapped_column(String(16), default="product")  # product | chat
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("quantity BETWEEN 1 AND 10", name="quantity"),
        Index("uq_cart_items_line", "cart_id", "variant_id", "store_id", unique=True),
    )


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(24), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="placed")
    subtotal: Mapped[int] = mapped_column(Integer)  # rupees
    item_count: Mapped[int] = mapped_column(Integer)

    items: Mapped[list["OrderItem"]] = relationship(
        order_by="OrderItem.id", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("status IN ('placed','fulfilled','cancelled','returned')", name="status"),
    )


class OrderItem(Base):
    """Snapshots name, size, colour and price at purchase time."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    quantity: Mapped[int] = mapped_column(SmallInteger)
    unit_price: Mapped[int] = mapped_column(Integer)
    product_name: Mapped[str] = mapped_column(String(160))
    size: Mapped[str] = mapped_column(String(16))
    colour: Mapped[str] = mapped_column(String(40))
    returned: Mapped[bool] = mapped_column(default=False, server_default="false")

    __table_args__ = (CheckConstraint("quantity > 0 AND unit_price > 0", name="positive"),)
