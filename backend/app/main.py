import mimetypes
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.routes import admin, auth, catalogue, chat, commerce, health
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.db.session import engine
from app.ml.embeddings import embed_query

mimetypes.add_type("image/webp", ".webp")


class CachedStaticFiles(StaticFiles):
    """Product images are content-addressed by slug and never change in place."""

    async def get_response(self, path, scope):  # noqa: ANN001, ANN201
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response


async def _connect_queue(redis_url: str) -> ArqRedis | None:
    try:
        return await create_pool(RedisSettings.from_dsn(redis_url), retry=0)
    except Exception:  # noqa: BLE001 - search works without the queue
        get_logger("gabriella").warning("queue_unavailable", redis_url=redis_url)
        return None


def _warm_query_encoder() -> None:
    try:
        embed_query("warm up")
    except Exception:  # noqa: BLE001
        get_logger("gabriella").warning("query_encoder_warmup_failed", exc_info=True)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    log = get_logger("gabriella")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("startup", env=settings.env, embeddings=settings.embedding_backend)
        app.state.arq = await _connect_queue(settings.redis_url)
        if settings.env != "test":
            # Load the CLIP text encoder off the request path so the first search is fast.
            threading.Thread(target=_warm_query_encoder, daemon=True).start()
        yield
        if app.state.arq is not None:
            await app.state.arq.aclose()
        await engine.dispose()

    app = FastAPI(
        title="Gabriella API",
        version="0.1.0",
        description="Inventory-aware fashion sales assistant for a simulated retailer.",
        lifespan=lifespan,
    )
    install_error_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["content-type", "x-request-id"],
        expose_headers=["x-request-id"],
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    for router in (auth.router, catalogue.router, chat.router, commerce.router, admin.router):
        app.include_router(router, prefix="/api")

    settings.media_root.mkdir(parents=True, exist_ok=True)
    app.mount(settings.media_url, CachedStaticFiles(directory=settings.media_root), name="media")

    Instrumentator(excluded_handlers=["/metrics", "/healthz", "/readyz", "/media.*"]).instrument(
        app
    ).expose(app, include_in_schema=False)
    return app


app = create_app()
