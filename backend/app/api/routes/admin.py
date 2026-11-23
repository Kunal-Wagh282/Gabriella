from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field, model_validator
from sqlalchemy import select

from app.api.deps import AdminUser, SessionDep
from app.core.errors import ServiceUnavailable
from app.db.models import Inventory, Store
from app.schemas.catalogue import StoreStock
from app.schemas.common import ApiModel
from app.services.inventory import adjust_stock

router = APIRouter(prefix="/admin", tags=["admin"])


class StockAdjustment(ApiModel):
    variant_id: int
    store_id: int
    delta: int | None = Field(None, ge=-10_000, le=10_000)
    set_to: int | None = Field(None, ge=0, le=10_000)
    reason: Literal["restock", "adjustment", "return"] = "restock"
    note: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def _one_of(self) -> "StockAdjustment":
        if (self.delta is None) == (self.set_to is None):
            raise ValueError("Provide exactly one of delta or set_to")
        return self


class StockAdjustmentOut(ApiModel):
    variant_id: int
    store_id: int
    on_hand: int


@router.post("/inventory/adjust", response_model=StockAdjustmentOut)
async def adjust_inventory(body: StockAdjustment, admin: AdminUser, session: SessionDep):
    delta = body.delta
    if body.set_to is not None:
        current = await session.scalar(
            select(Inventory.on_hand)
            .where(Inventory.variant_id == body.variant_id, Inventory.store_id == body.store_id)
            .with_for_update()
        )
        delta = body.set_to - (current or 0)
    row = await adjust_stock(
        session,
        variant_id=body.variant_id,
        store_id=body.store_id,
        delta=delta or 0,
        reason=body.reason,
        reference=body.note,
        actor_user_id=admin.id,
    )
    await session.commit()
    return StockAdjustmentOut(variant_id=row.variant_id, store_id=row.store_id, on_hand=row.on_hand)


@router.get("/inventory/{variant_id}", response_model=list[StoreStock])
async def variant_inventory(variant_id: int, _: AdminUser, session: SessionDep):
    rows = await session.execute(
        select(Inventory.store_id, Store.code, Inventory.on_hand)
        .join(Store, Store.id == Inventory.store_id)
        .where(Inventory.variant_id == variant_id)
        .order_by(Store.id)
    )
    return [StoreStock(store_id=s, store_code=c, on_hand=n) for s, c, n in rows.all()]


class EmbeddingRebuild(ApiModel):
    force: bool = False
    product_ids: list[int] | None = None


class JobQueued(ApiModel):
    job_id: str
    status: str


@router.post("/embeddings/rebuild", response_model=JobQueued, status_code=202)
async def rebuild_embeddings(body: EmbeddingRebuild, request: Request, _: AdminUser):
    """Queue an embedding sync on the worker. Unchanged products are skipped unless `force`."""
    pool = getattr(request.app.state, "arq", None)
    if pool is None:
        raise ServiceUnavailable("Background worker queue is not available")
    job = await pool.enqueue_job("embed_products", body.product_ids, body.force)
    return JobQueued(job_id=job.job_id if job else "duplicate", status="queued")
