import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, Unauthorized
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.db.models import AuthSession, User, UserPreferences

log = get_logger("gabriella.auth")
# Verifying against a real hash keeps response time similar for unknown emails.
_DUMMY_HASH = hash_password("timing-equaliser")


@dataclass
class IssuedTokens:
    access_token: str
    access_expires: datetime
    refresh_token: str
    refresh_expires: datetime


async def register(session: AsyncSession, *, email: str, password: str, full_name: str) -> User:
    user = User(email=email.lower(), password_hash=hash_password(password), full_name=full_name)
    user.preferences = UserPreferences(personalization_enabled=True)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("An account with this email already exists") from exc
    log.info("user_registered", user_id=str(user.id))
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise Unauthorized("Incorrect email or password")
    if not verify_password(password, user.password_hash) or not user.is_active:
        raise Unauthorized("Incorrect email or password")
    return user


async def issue_tokens(
    session: AsyncSession, user: User, *, user_agent: str | None = None
) -> IssuedTokens:
    settings = get_settings()
    access, access_exp = create_access_token(user.id, is_admin=user.is_admin)
    raw, digest = new_refresh_token()
    refresh_exp = datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=digest,
            user_agent=(user_agent or "")[:255] or None,
            expires_at=refresh_exp,
        )
    )
    await session.flush()
    return IssuedTokens(access, access_exp, raw, refresh_exp)


async def rotate_refresh(
    session: AsyncSession, raw_token: str, *, user_agent: str | None = None
) -> tuple[User, IssuedTokens]:
    """Exchange a refresh token for a new pair. Replaying a revoked token revokes them all."""
    now = datetime.now(UTC)
    record = await session.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_refresh_token(raw_token))
    )
    if record is None:
        raise Unauthorized("Session expired, please sign in again")
    if record.revoked_at is not None:
        await revoke_all(session, record.user_id)
        log.warning("refresh_token_reuse", user_id=str(record.user_id))
        raise Unauthorized("Session expired, please sign in again")
    if record.expires_at <= now:
        raise Unauthorized("Session expired, please sign in again")

    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Session expired, please sign in again")
    record.revoked_at = now
    return user, await issue_tokens(session, user, user_agent=user_agent)


async def revoke(session: AsyncSession, raw_token: str) -> None:
    await session.execute(
        update(AuthSession)
        .where(
            AuthSession.token_hash == hash_refresh_token(raw_token),
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_all(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
