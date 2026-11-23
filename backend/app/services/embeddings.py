"""Keeps `product_embeddings` in step with the catalogue.

Idempotent: each row stores a hash of (model, text document, image URL), so re-running only
embeds products whose content changed. Sold-out products keep their vectors; only stock
filters at query time decide availability.
"""

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from anyio import to_thread
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Product, ProductEmbedding
from app.ml.embeddings import Embedder
from app.retrieval.documents import product_document

log = get_logger("gabriella.embeddings")
BATCH = 64


@dataclass
class SyncReport:
    checked: int = 0
    embedded: int = 0
    missing_images: int = 0
    seconds: float = 0.0


def _image_path(url: str | None) -> Path | None:
    if not url:
        return None
    settings = get_settings()
    rel = url.removeprefix(settings.media_url).lstrip("/")
    path = settings.media_root / rel
    return path if path.exists() else None


async def sync_embeddings(
    session: AsyncSession,
    embedder: Embedder,
    *,
    product_ids: list[int] | None = None,
    force: bool = False,
) -> SyncReport:
    start = time.perf_counter()
    report = SyncReport()
    stmt = select(Product).options(selectinload(Product.images)).order_by(Product.id)
    if product_ids:
        stmt = stmt.where(Product.id.in_(product_ids))
    products = list((await session.scalars(stmt)).unique().all())
    existing = dict(
        (
            await session.execute(
                select(ProductEmbedding.product_id, ProductEmbedding.content_hash)
            )
        ).all()
    )

    pending: list[tuple[Product, str, Path | None, str]] = []
    for p in products:
        report.checked += 1
        doc = product_document(p)
        flatlay = next((i.url for i in p.images if i.kind == "flatlay"), None)
        digest = hashlib.sha256(f"{embedder.name}|{doc}|{flatlay}".encode()).hexdigest()
        if not force and existing.get(p.id) == digest:
            continue
        image = _image_path(flatlay)
        report.missing_images += image is None
        pending.append((p, doc, image, digest))

    for i in range(0, len(pending), BATCH):
        batch = pending[i : i + BATCH]
        text_vecs = await to_thread.run_sync(embedder.embed_texts, [doc for _, doc, _, _ in batch])
        with_images = [(j, img) for j, (_, _, img, _) in enumerate(batch) if img is not None]
        image_vecs = await to_thread.run_sync(
            embedder.embed_images, [img for _, img in with_images]
        )
        image_by_index = {j: vec for (j, _), vec in zip(with_images, image_vecs, strict=True)}

        rows = [
            {
                "product_id": p.id,
                "text_embedding": text_vecs[j],
                "image_embedding": image_by_index.get(j),
                "model_name": embedder.name,
                "content_hash": digest,
            }
            for j, (p, _, _, digest) in enumerate(batch)
        ]
        stmt = insert(ProductEmbedding).values(rows)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[ProductEmbedding.product_id],
                set_={
                    c: stmt.excluded[c]
                    for c in ("text_embedding", "image_embedding", "model_name", "content_hash")
                },
            )
        )
        await session.commit()
        report.embedded += len(batch)
        log.info("embeddings_batch", done=report.embedded, total=len(pending))

    report.seconds = round(time.perf_counter() - start, 2)
    log.info("embeddings_synced", **report.__dict__, model=embedder.name)
    return report
