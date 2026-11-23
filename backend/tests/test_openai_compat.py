"""The OpenAI-compatible backend (Groq, Ollama, …): message translation, lenient parsing,
retries, provider selection, and one full agent turn driven through it."""

import json
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import llm
from app.agent.llm import block, tool_use
from app.agent.loop import run_llm_turn
from app.agent.openai_compat import (
    OpenAICompatibleBackend,
    from_openai_response,
    parse_arguments,
    to_openai_messages,
    to_openai_tools,
)
from app.agent.tools import TOOL_DEFINITIONS, ToolContext
from app.core.config import get_settings
from app.db.models import Store
from tests.conftest import Catalogue


def _response(
    *,
    content: str | None = None,
    calls: list[tuple[str, str, str]] = (),
    finish: str = "tool_calls",
) -> Any:
    tool_calls = [
        SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=args))
        for cid, name, args in calls
    ] or None
    return SimpleNamespace(
        model="llama-3.3-70b-versatile",
        choices=[
            SimpleNamespace(
                finish_reason=finish,
                message=SimpleNamespace(content=content, tool_calls=tool_calls),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=900,
            completion_tokens=40,
            prompt_tokens_details=SimpleNamespace(cached_tokens=600),
        ),
    )


class FakeCompletions:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    async def create(self, **request: Any) -> Any:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _backend(responses: list[Any]) -> tuple[OpenAICompatibleBackend, FakeCompletions]:
    backend = OpenAICompatibleBackend(
        provider="groq", base_url="http://unused", api_key="x", model="m"
    )
    fake = FakeCompletions(responses)
    backend._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))  # type: ignore[assignment]
    return backend, fake


def test_tools_translate_to_function_schemas():
    tools = to_openai_tools(TOOL_DEFINITIONS)
    assert {t["function"]["name"] for t in tools} >= {"search_catalogue", "present_recommendation"}
    assert all(
        t["type"] == "function" and "eager_input_streaming" not in t["function"] for t in tools
    )
    assert tools[0]["function"]["parameters"]["type"] == "object"


def test_messages_translate_tool_turns():
    messages = [
        {"role": "user", "content": "chinos?"},
        {
            "role": "assistant",
            "content": [
                block(type="text", text="Looking."),
                tool_use("search_catalogue", {"query": "chinos"}, id="c1"),
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": '{"products":[]}'},
                {"type": "tool_result", "tool_use_id": "c2", "content": "bad", "is_error": True},
            ],
        },
        {"role": "assistant", "content": "Earlier answer"},
    ]
    out = to_openai_messages("SYSTEM", messages)
    assert out[0] == {"role": "system", "content": "SYSTEM"}
    assert out[2]["tool_calls"][0]["function"] == {
        "name": "search_catalogue",
        "arguments": '{"query": "chinos"}',
    }
    assert out[2]["content"] == "Looking."
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"products":[]}'}
    assert out[4]["content"].startswith("ERROR:")
    assert out[5] == {"role": "assistant", "content": "Earlier answer"}


def test_lenient_argument_parsing():
    assert parse_arguments('{"query": "x", "filters": "{\\"size\\": \\"M\\"}"}') == {
        "query": "x",
        "filters": {"size": "M"},
    }
    assert parse_arguments("") == {}
    assert "_unparseable_arguments" in parse_arguments("{not json")
    assert "_unparseable_arguments" in parse_arguments("[1, 2]")


def test_response_translation():
    turn = from_openai_response(
        _response(content="Sure", calls=[("c9", "get_product", '{"product_id": 5}')], finish="stop")
    )
    assert turn.stop_reason == "tool_use"  # tool calls win over a "stop" finish reason
    text, call = turn.content
    assert text.text == "Sure" and (call.id, call.name, call.input) == (
        "c9",
        "get_product",
        {"product_id": 5},
    )
    assert (turn.usage.input_tokens, turn.usage.output_tokens, turn.usage.cache_read_tokens) == (
        900,
        40,
        600,
    )
    assert (
        from_openai_response(_response(content="hi", finish="length")).stop_reason == "max_tokens"
    )
    assert (
        from_openai_response(_response(content="no", finish="content_filter")).stop_reason
        == "refusal"
    )


def _tool_use_failed() -> openai.BadRequestError:
    request = httpx.Request("POST", "http://unused")
    response = httpx.Response(400, request=request, json={"error": {"code": "tool_use_failed"}})
    return openai.BadRequestError("Error code: 400 - tool_use_failed", response=response, body=None)


async def test_tool_format_failures_are_retried():
    backend, fake = _backend([_tool_use_failed(), _response(content="ok", finish="stop")])
    turn = await backend.complete(
        system="s", tools=TOOL_DEFINITIONS, messages=[{"role": "user", "content": "hi"}]
    )
    assert turn.content[0].text == "ok" and len(fake.requests) == 2
    assert fake.requests[0]["tool_choice"] == "auto"


async def test_full_agent_turn_through_openai_format(session: AsyncSession, catalogue: Catalogue):
    present = {
        "message": "Navy linen works for dinner.",
        "groups": [
            {
                "title": "Pick",
                "kind": "picks",
                "items": [
                    {
                        "product_id": catalogue.navy_shirt,
                        "role": "pick",
                        "reason": "Breathable linen",
                    }
                ],
            }
        ],
        "constraints": {"apparel_size": "M"},
        "follow_ups": [],
    }
    backend, fake = _backend(
        [
            # A smaller model sending the nested filters object as a string still works.
            _response(
                calls=[
                    (
                        "c1",
                        "search_catalogue",
                        json.dumps({"query": "linen shirt", "filters": json.dumps({"size": "M"})}),
                    )
                ]
            ),
            _response(calls=[("c2", "present_recommendation", json.dumps(present))]),
        ]
    )
    stores = {s.code: s for s in (await session.scalars(select(Store))).all()}
    ctx = ToolContext(session=session, store=stores["PUN"], stores=stores)

    async def emit(_: dict[str, Any]) -> None:
        return None

    result = await run_llm_turn(backend, ctx, [], "linen shirt in M", emit)
    assert result.validation["passed_first_time"] is True
    assert (
        result.recommendation.groups[0].items[0].variant_id
        == catalogue.variants["navy-linen-shirt:M"]
    )
    second = fake.requests[1]["messages"]
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "c1"
    assert '"in_stock_sizes"' in second[-1]["content"]


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, None),
        ({"GROQ_API_KEY": "gsk_test"}, "groq:llama-3.3-70b-versatile"),
        (
            {"GROQ_API_KEY": "gsk_test", "ANTHROPIC_API_KEY": "sk-ant"},
            "groq:llama-3.3-70b-versatile",
        ),
        ({"ANTHROPIC_API_KEY": "sk-ant"}, "claude-sonnet-5-5"),
        ({"LLM_PROVIDER": "ollama"}, "ollama:qwen2.5:7b"),
        ({"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "qwen2.5:3b"}, "ollama:qwen2.5:3b"),
        (
            {
                "LLM_PROVIDER": "openai_compatible",
                "LLM_BASE_URL": "http://vllm:8000/v1",
                "LLM_MODEL": "x",
            },
            "openai_compatible:x",
        ),
        ({"LLM_PROVIDER": "none", "GROQ_API_KEY": "gsk_test"}, None),
    ],
)
def test_provider_selection(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str | None
):
    for key in (
        "GROQ_API_KEY",
        "ANTHROPIC_API_KEY",
        "LLM_PROVIDER",
        "OLLAMA_MODEL",
        "LLM_BASE_URL",
        "LLM_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # Ignore any developer .env file so the test sees only the variables above.
    monkeypatch.setitem(
        get_settings.__wrapped__.__globals__["Settings"].model_config, "env_file", None
    )
    get_settings.cache_clear()
    llm.default_backend.cache_clear()
    try:
        backend = llm.default_backend()
        assert (backend.name if backend else None) == expected
    finally:
        get_settings.cache_clear()
        llm.default_backend.cache_clear()
