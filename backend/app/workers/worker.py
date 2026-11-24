"""Background worker (arq on Redis).

arq app.workers.worker.WorkerSettings      # run the worker
python -m app.workers.embed [--force]      # one-off sync without Redis
"""

from datetime import UTC, datetime
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.models import Upload
from app.db.session import SessionLocal, engine
from app.ml.embeddings import get_embedder
from app.services.embeddings import sync_embeddings
from app.vision.garment import upload_path

log = get_logger("gabriella.worker")


async def embed_products(
    ctx: dict[str, Any], product_ids: list[int] | None = None, force: bool = False
) -> dict[str, Any]:
    async with SessionLocal() as session:
        report = await sync_embeddings(
            session, get_embedder(), product_ids=product_ids, force=force
        )
    return report.__dict__


async def purge_expired_uploads(ctx: dict[str, Any]) -> int:
    """Shoppers' photos are kept for 24 hours only: delete the files and their rows."""
    async with SessionLocal() as session:
        expired = (
            await session.scalars(select(Upload).where(Upload.expires_at < datetime.now(UTC)))
        ).all()
        for upload in expired:
            upload_path(upload.file_name).unlink(missing_ok=True)
            await session.delete(upload)
        await session.commit()
    if expired:
        log.info("uploads_purged", count=len(expired))
    return len(expired)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    log.info("worker_startup", backend=settings.embedding_backend)
    # Catch up on anything seeded or edited while the worker was down.
    await embed_products(ctx)
    await purge_expired_uploads(ctx)


async def shutdown(ctx: dict[str, Any]) -> None:
    await engine.dispose()


class WorkerSettings:
    functions = [embed_products, purge_expired_uploads]
    on_startup = startup
    on_shutdown = shutdown
    # Hourly safety net; a no-op when every content hash matches.
    cron_jobs = [
        cron(embed_products, minute=7, run_at_startup=False),
        cron(purge_expired_uploads, minute={0, 30}, run_at_startup=False),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 2
    job_timeout = 1800
