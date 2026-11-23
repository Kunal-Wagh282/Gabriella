import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Store(TimestampMixin, Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(255))
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Inventory(Base):
    """Stock on hand for one variant at one store. The source of truth for availability."""

    __tablename__ = "inventory"

    variant_id: Mapped[int] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE"), primary_key=True
    )
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), primary_key=True)
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Not eager-joined: stock rows are locked with FOR UPDATE, which rejects outer joins.
    store: Mapped[Store] = relationship(lazy="raise")

    __table_args__ = (
        CheckConstraint("on_hand >= 0", name="on_hand_non_negative"),
        # Hot path for "in stock at store X" filters.
        Index(
            "ix_inventory_store_in_stock",
            "store_id",
            "variant_id",
            postgresql_where=text("on_hand > 0"),
        ),
    )


class InventoryMovement(Base):
    """Append-only audit trail of every stock change."""

    __tablename__ = "inventory_movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    delta: Mapped[int] = mapped_column(Integer)
    on_hand_after: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(16))  # seed | restock | sale | adjustment
    reference: Mapped[str | None] = mapped_column(String(64))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("reason IN ('seed','restock','sale','adjustment','return')", name="reason"),
    )
