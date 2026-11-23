"""Synchronously embed the catalogue without a worker: `python -m app.workers.embed [--force]`."""

import argparse
import asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal, engine
from app.ml.embeddings import get_embedder
from app.services.embeddings import sync_embeddings


async def main(force: bool) -> None:
    async with SessionLocal() as session:
        report = await sync_embeddings(session, get_embedder(), force=force)
    await engine.dispose()
    print(
        f"embeddings: checked {report.checked}, embedded {report.embedded}, "
        f"missing images {report.missing_images}, {report.seconds}s"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-embed even if unchanged")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level, json=False)
    asyncio.run(main(args.force))
