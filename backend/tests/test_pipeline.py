"""Pipeline mode: the server drafts, the model refines in one call, the validator has the last word."""

import json
from typing import Any

import httpx
import openai
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import ModelTurn, ScriptedBackend, tool_use
from app.api.routes import chat as chat_routes
from app.db.models import AgentTrace
from tests.conftest import Catalogue


async def _turn(client: httpx.AsyncClient, catalogue: Catalogue, text: str) -> dict[str, Any]:
    sid = (await client.post("/api/chat/sessions", json={"store_id": catalogue.pune})).json()["id"]
    events = []
    async with client.stream(
        "POST", f"/api/chat/sessions/{sid}/messages", json={"text": text}
    ) as r:
        async for line in r.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events[-1]


def _present(items: list[dict[str, Any]], **constraints: Any) -> ModelTurn:
    return ModelTurn(
        content=[
            tool_use(
                "present_recommendation",
                {
                    "message": "A sharp office look.",
                    "groups": [{"title": "Office look", "kind": "outfit", "items": items}],
                    "constraints": constraints,
                    "follow_ups": ["Make it less formal"],
                },
                id="p1",
            )
        ],
        stop_reason="tool_use",
    )


async def test_model_refines_the_draft_in_one_call(
    client: httpx.AsyncClient,
    session: AsyncSession,
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
):
    backend = ScriptedBackend(
        [
            _present(
                [
                    {
                        "product_id": catalogue.navy_shirt,
                        "role": "top",
                        "reason": "Navy linen reads polished",
                    },
                    {
                        "product_id": catalogue.beige_chinos,
                        "role": "bottom",
                        "reason": "Beige keeps it light",
                    },
                    {
                        "product_id": catalogue.white_sneakers,
                        "role": "footwear",
                        "reason": "Clean white finish",
                    },
                ],
                occasion="office",
                gender="men",
            )
        ]
    )
    monkeypatch.setattr(chat_routes, "default_backend", lambda: backend)
    event = await _turn(client, catalogue, "office outfit for men")

    message = event["message"]
    assert message["content"] == "A sharp office look."
    assert [i["reason"] for i in message["groups"][0]["items"]][0] == "Navy linen reads polished"
    # The model saw the draft and only the present tool, in a single request.
    (request,) = backend.requests
    assert "<draft>" in request[-1]["content"] and "<candidates>" in request[-1]["content"]
    trace = (await session.scalars(select(AgentTrace))).one()
    assert trace.mode == "llm" and trace.model_requests == 1
    assert trace.validation["strategy"] == "pipeline"


async def test_rate_limited_model_still_gets_a_validated_answer(
    client: httpx.AsyncClient,
    session: AsyncSession,
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
):
    class RateLimited:
        name = "groq:test"

        async def complete(self, **_: Any) -> ModelTurn:
            request = httpx.Request("POST", "http://groq")
            raise openai.RateLimitError(
                "rate limited", response=httpx.Response(429, request=request), body=None
            )

    monkeypatch.setattr(chat_routes, "default_backend", lambda: RateLimited())
    event = await _turn(client, catalogue, "office outfit for men")
    assert event["type"] == "message" and len(event["message"]["groups"][0]["items"]) == 3
    trace = (await session.scalars(select(AgentTrace))).one()
    assert trace.mode == "fallback" and "RateLimitError" in trace.error
    assert trace.validation["strategy"] == "pipeline-draft"


async def test_sizes_stay_enforced_when_the_model_drops_them(
    client: httpx.AsyncClient, catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
):
    # The shopper said "M"; the model's constraints forget it and it picks the chinos,
    # whose M is sold out in Pune. The merged constraints catch it and the item is swapped/dropped.
    backend = ScriptedBackend(
        [
            _present(
                [
                    {"product_id": catalogue.navy_shirt, "role": "top", "reason": "Navy"},
                    {"product_id": catalogue.beige_chinos, "role": "bottom", "reason": "Beige"},
                ]
            )
        ]
    )
    monkeypatch.setattr(chat_routes, "default_backend", lambda: backend)
    event = await _turn(client, catalogue, "office outfit for men, I wear M and UK 9")
    items = event["message"]["groups"][0]["items"] if event["message"]["groups"] else []
    assert catalogue.beige_chinos not in [i["product"]["id"] for i in items]
    assert all(i["variant"] and i["variant"]["in_stock"] for i in items)
    assert event["constraints"]["apparel_size"] == "M"


async def test_invented_products_are_rejected_in_pipeline_mode(
    client: httpx.AsyncClient, catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
):
    backend = ScriptedBackend(
        [
            _present([{"product_id": 987654, "role": "top", "reason": "Invented"}]),
            _present([{"product_id": catalogue.navy_shirt, "role": "top", "reason": "Real"}]),
        ]
    )
    monkeypatch.setattr(chat_routes, "default_backend", lambda: backend)
    event = await _turn(client, catalogue, "office outfit for men")
    assert [i["product"]["id"] for i in event["message"]["groups"][0]["items"]] == [
        catalogue.navy_shirt
    ]
    assert "does not exist" in backend.requests[1][-1]["content"][0]["content"]


async def test_plain_text_reply_falls_back_to_the_draft(
    client: httpx.AsyncClient,
    session: AsyncSession,
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.agent.llm import block

    chatty = ModelTurn(
        content=[block(type="text", text="Could you tell me more?")], stop_reason="end_turn"
    )
    backend = ScriptedBackend([chatty, chatty])
    monkeypatch.setattr(chat_routes, "default_backend", lambda: backend)
    event = await _turn(client, catalogue, "office outfit for men")
    assert (
        len(event["message"]["groups"][0]["items"]) == 3
    )  # the draft outfit, not a vague question
    trace = (await session.scalars(select(AgentTrace))).one()
    assert trace.validation["strategy"] == "pipeline-draft"
    assert "present_recommendation" in trace.error


async def test_start_fresh_skips_the_model(
    client: httpx.AsyncClient,
    session: AsyncSession,
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
):
    backend = ScriptedBackend([])  # any model call would fail: there is no scripted turn
    monkeypatch.setattr(chat_routes, "default_backend", lambda: backend)
    event = await _turn(client, catalogue, "start fresh")
    assert event["type"] == "message"
    assert event["message"]["content"].startswith("Fresh start")
    assert event["message"]["groups"] == []
    trace = (await session.scalars(select(AgentTrace))).one()
    assert trace.validation["strategy"] == "pipeline-reset"
    assert trace.model_requests == 0


def test_keeps_the_cheapest_look_figure_the_model_dropped():
    from app.agent.pipeline import _keep_cheapest_look

    draft = "I couldn't fit a full outfit in stock at Pune within ₹2,000. The most affordable complete look here comes to about ₹7,097."
    kept = _keep_cheapest_look(draft, "Sorry, nothing fits that budget. Consider raising it.")
    assert kept.endswith("The most affordable complete look here comes to about ₹7,097.")
    already = "The cheapest complete look is ₹7,097."
    assert _keep_cheapest_look(draft, already) == already
    assert _keep_cheapest_look("Here's a dinner look.", "Enjoy!") == "Enjoy!"
