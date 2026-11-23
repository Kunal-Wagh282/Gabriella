import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ACCESS_COOKIE, REFRESH_COOKIE
from app.db.models import AuthSession
from tests.conftest import Catalogue, login, make_user


async def test_register_sets_cookies_and_me_works(client: httpx.AsyncClient):
    r = await client.post(
        "/api/auth/register",
        json={"email": "Asha@Example.com", "password": "long-enough", "full_name": " Asha "},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "asha@example.com"
    assert body["full_name"] == "Asha"
    assert body["preferences"]["personalization_enabled"] is True
    set_cookie = r.headers.get_list("set-cookie")
    assert any(c.startswith(f"{ACCESS_COOKIE}=") and "HttpOnly" in c for c in set_cookie)
    assert any(c.startswith(f"{REFRESH_COOKIE}=") and "Path=/api/auth" in c for c in set_cookie)

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "asha@example.com"


async def test_register_rejects_duplicate_email_and_weak_password(client: httpx.AsyncClient):
    payload = {"email": "dup@example.com", "password": "long-enough", "full_name": "A"}
    assert (await client.post("/api/auth/register", json=payload)).status_code == 201
    dup = await client.post("/api/auth/register", json={**payload, "email": "DUP@example.com"})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "conflict"

    weak = await client.post(
        "/api/auth/register", json={"email": "w@example.com", "password": "short", "full_name": "A"}
    )
    assert weak.status_code == 422
    assert weak.json()["error"]["code"] == "validation_error"


async def test_login_errors_do_not_reveal_which_field_was_wrong(
    client: httpx.AsyncClient, session: AsyncSession
):
    await make_user(session, "known@example.com")
    wrong_pw = await client.post(
        "/api/auth/login", json={"email": "known@example.com", "password": "nope"}
    )
    unknown = await client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "nope"}
    )
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_protected_route_requires_auth(client: httpx.AsyncClient):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["request_id"]


async def test_refresh_rotates_and_replay_revokes_everything(
    client: httpx.AsyncClient, session: AsyncSession
):
    await make_user(session, "rot@example.com")
    await login(client, "rot@example.com")
    first_refresh = client.cookies.get(REFRESH_COOKIE, path="/api/auth")

    r = await client.post("/api/auth/refresh")
    assert r.status_code == 200
    second_refresh = client.cookies.get(REFRESH_COOKIE, path="/api/auth")
    assert second_refresh and second_refresh != first_refresh

    # Replaying the already-used token looks like theft: every session is revoked.
    replay = httpx.AsyncClient(transport=client._transport, base_url="http://testserver")
    replay.cookies.set(REFRESH_COOKIE, first_refresh, path="/api/auth")
    assert (await replay.post("/api/auth/refresh")).status_code == 401
    await replay.aclose()

    assert (await client.post("/api/auth/refresh")).status_code == 401
    active = await session.scalar(
        select(func.count()).select_from(AuthSession).where(AuthSession.revoked_at.is_(None))
    )
    assert active == 0


async def test_logout_revokes_refresh_token(client: httpx.AsyncClient, session: AsyncSession):
    await make_user(session, "out@example.com")
    await login(client, "out@example.com")
    raw = client.cookies.get(REFRESH_COOKIE, path="/api/auth")
    assert (await client.post("/api/auth/logout")).status_code == 204

    client.cookies.set(REFRESH_COOKIE, raw, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_preferences_update(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    await make_user(session, "prefs@example.com")
    await login(client, "prefs@example.com")

    r = await client.patch(
        "/api/me/preferences",
        json={"preferred_store_id": catalogue.pune, "personalization_enabled": False},
    )
    assert r.status_code == 200
    assert r.json() == {"preferred_store_id": catalogue.pune, "personalization_enabled": False}

    missing = await client.patch("/api/me/preferences", json={"preferred_store_id": 99999})
    assert missing.status_code == 404


def test_seed_account_emails_pass_login_validation():
    """Reserved TLDs such as .test are rejected by the validator, which once locked out the demo."""
    from app.core.config import get_settings
    from app.schemas.auth import LoginRequest

    settings = get_settings()
    for email in (settings.seed_admin_email, settings.seed_demo_email):
        LoginRequest(email=email, password="x")
