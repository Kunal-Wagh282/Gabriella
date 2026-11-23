from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.test_database_url if _settings.env == "test" else _settings.database_url,
    pool_pre_ping=True,
    # Tests run each case against a fresh connection to avoid cross-loop pool reuse.
    **({"poolclass": NullPool} if _settings.env == "test" else {"pool_size": 10}),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
