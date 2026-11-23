from fastapi import APIRouter, Request, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.core.config import get_settings
from app.core.errors import NotFound, Unauthorized
from app.core.security import ACCESS_COOKIE, REFRESH_COOKIE, REFRESH_COOKIE_PATH
from app.db.models import Store
from app.schemas.auth import (
    LoginRequest,
    PreferencesOut,
    PreferencesUpdate,
    RegisterRequest,
    UserOut,
)
from app.services import auth as auth_service
from app.services.auth import IssuedTokens

router = APIRouter(tags=["auth"])


def _set_cookies(response: Response, tokens: IssuedTokens) -> None:
    secure = get_settings().cookie_secure
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access_token,
        expires=tokens.access_expires,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        expires=tokens.refresh_expires,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest, request: Request, response: Response, session: SessionDep
):
    user = await auth_service.register(
        session, email=body.email, password=body.password, full_name=body.full_name
    )
    tokens = await auth_service.issue_tokens(
        session, user, user_agent=request.headers.get("user-agent")
    )
    await session.commit()
    _set_cookies(response, tokens)
    await session.refresh(user, ["preferences"])
    return user


@router.post("/auth/login", response_model=UserOut)
async def login(body: LoginRequest, request: Request, response: Response, session: SessionDep):
    user = await auth_service.authenticate(session, email=body.email, password=body.password)
    tokens = await auth_service.issue_tokens(
        session, user, user_agent=request.headers.get("user-agent")
    )
    await session.commit()
    _set_cookies(response, tokens)
    return user


@router.post("/auth/refresh", response_model=UserOut)
async def refresh(request: Request, response: Response, session: SessionDep):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise Unauthorized("Session expired, please sign in again")
    try:
        user, tokens = await auth_service.rotate_refresh(
            session, raw, user_agent=request.headers.get("user-agent")
        )
    except Unauthorized:
        await session.commit()  # persist reuse-detection revocations
        raise
    await session.commit()
    _set_cookies(response, tokens)
    return user


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: SessionDep) -> Response:
    if raw := request.cookies.get(REFRESH_COOKIE):
        await auth_service.revoke(session, raw)
        await session.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    _clear_cookies(response)
    return response


@router.get("/auth/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user


@router.get("/me/preferences", response_model=PreferencesOut)
async def get_preferences(user: CurrentUser):
    return user.preferences


@router.patch("/me/preferences", response_model=PreferencesOut)
async def update_preferences(body: PreferencesUpdate, user: CurrentUser, session: SessionDep):
    prefs = user.preferences
    changes = body.model_dump(exclude_unset=True)
    if "preferred_store_id" in changes:
        store_id = changes["preferred_store_id"]
        if store_id is not None and await session.get(Store, store_id) is None:
            raise NotFound("Store not found")
        prefs.preferred_store_id = store_id
    if changes.get("personalization_enabled") is not None:
        prefs.personalization_enabled = changes["personalization_enabled"]
    await session.commit()
    return prefs
