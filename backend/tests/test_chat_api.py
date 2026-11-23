import json
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import ModelTurn, ScriptedBackend, tool_use
from app.api.routes import chat as chat_routes
from app.db.models import AgentTrace
from tests.conftest import Catalogue, login, make_user


async def _send(
    client: httpx.AsyncClient, sid: str, text: str, **extra: Any
) -> list[dict[str, Any]]:
    events = []
    async with client.stream(
        "POST", f"/api/chat/sessions/{sid}/messages", json={"text": text, **extra}
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        async for line in r.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


async def _session(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    r = await client.post("/api/chat/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_fallback_turn_streams_validated_outfit(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    chat = await _session(client, store_id=catalogue.pune)
    assert chat["mode"] == "fallback"
    events = await _send(client, chat["id"], "office outfit for men")
    assert events[0]["type"] == "status" and events[-1]["type"] == "message"
    message = events[-1]["message"]
    (group,) = message["groups"]
    ids = {i["product"]["id"] for i in group["items"]}
    assert ids == {catalogue.navy_shirt, catalogue.beige_chinos, catalogue.white_sneakers}
    assert group["total"] == 1999 + 2499 + 3999
    assert all(i["product"]["in_stock"] for i in group["items"])
    assert events[-1]["constraints"]["occasion"] == "office"

    trace = (await session.scalars(select(AgentTrace))).one()
    assert trace.mode == "fallback" and trace.validation["checked_items"] == 3


async def test_history_is_rehydrated_with_live_stock(
    client: httpx.AsyncClient, catalogue: Catalogue
):
    chat = await _session(client, store_id=catalogue.pune, product="beige-chinos")
    assert chat["context_product"]["id"] == catalogue.beige_chinos
    await _send(client, chat["id"], "Do you have these in M?")
    body = (await client.get(f"/api/chat/sessions/{chat['id']}")).json()
    user, assistant = body["messages"]
    assert user["role"] == "user" and assistant["role"] == "assistant"
    assert "sold out at Pune" in assistant["content"] and "Mumbai" in assistant["content"]


async def test_llm_turn_end_to_end_with_scripted_model(
    client: httpx.AsyncClient,
    session: AsyncSession,
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
):
    backend = ScriptedBackend(
        [
            ModelTurn(
                content=[
                    tool_use(
                        "search_catalogue",
                        {"query": "sneakers", "filters": {"size": "UK 9"}},
                        id="a",
                    )
                ],
                stop_reason="tool_use",
            ),
            ModelTurn(
                content=[
                    tool_use(
                        "present_recommendation",
                        {
                            "message": "These white sneakers are in your size.",
                            "groups": [
                                {
                                    "title": "Sneakers",
                                    "kind": "picks",
                                    "items": [
                                        {
                                            "product_id": catalogue.white_sneakers,
                                            "role": "pick",
                                            "reason": "Clean and versatile",
                                        }
                                    ],
                                }
                            ],
                            "constraints": {"footwear_size": "UK 9"},
                            "follow_ups": ["Build an outfit"],
                        },
                        id="b",
                    )
                ],
                stop_reason="tool_use",
            ),
        ]
    )
    monkeypatch.setattr(chat_routes, "default_backend", lambda: backend)
    chat = await _session(client, store_id=catalogue.pune)
    events = await _send(client, chat["id"], "white sneakers in UK 9")
    item = events[-1]["message"]["groups"][0]["items"][0]
    assert item["variant"] == {
        "id": catalogue.variants["white-sneakers:UK 9"],
        "size": "UK 9",
        "in_stock": True,
    }
    # The model saw the session context (store) in the user turn, not the system prompt.
    assert (
        "Gabriella Koregaon" not in str(backend.requests[0][0])
        or "<session>" in backend.requests[0][0]["content"]
    )
    trace = (await session.scalars(select(AgentTrace))).one()
    assert trace.mode == "llm" and trace.model_requests == 2
    assert [c["name"] for c in trace.tool_calls] == ["search_catalogue", "present_recommendation"]


async def test_model_failure_degrades_to_fallback(
    client: httpx.AsyncClient,
    session: AsyncSession,
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
):
    class Broken:
        name = "broken"

        async def complete(self, **_: Any) -> ModelTurn:
            raise ConnectionError("API unreachable")

    monkeypatch.setattr(chat_routes, "default_backend", lambda: Broken())
    chat = await _session(client, store_id=catalogue.pune)
    events = await _send(client, chat["id"], "sneakers")
    assert events[-1]["type"] == "message"
    trace = (await session.scalars(select(AgentTrace))).one()
    assert trace.mode == "fallback" and "ConnectionError" in trace.error


async def test_signed_in_sessions_are_private(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    await make_user(session, "owner@example.com")
    await login(client, "owner@example.com")
    chat = await _session(client)
    assert (await client.get(f"/api/chat/sessions/{chat['id']}")).status_code == 200

    stranger = httpx.AsyncClient(transport=client._transport, base_url="http://testserver")
    assert (await stranger.get(f"/api/chat/sessions/{chat['id']}")).status_code == 404
    r = await stranger.post(f"/api/chat/sessions/{chat['id']}/messages", json={"text": "hi"})
    assert r.status_code == 404
    await stranger.aclose()


async def test_input_validation(client: httpx.AsyncClient, catalogue: Catalogue):
    chat = await _session(client)
    r = await client.post(f"/api/chat/sessions/{chat['id']}/messages", json={"text": ""})
    assert r.status_code == 422
    assert (await client.post("/api/chat/sessions", json={"store_id": 999})).status_code == 404
