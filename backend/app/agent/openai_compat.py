"""Backend for any OpenAI-compatible chat API: Groq, Ollama, OpenRouter, vLLM, LM Studio.

The agent loop speaks one internal format (assistant `tool_use` blocks, user `tool_result`
blocks). This module translates it to and from the OpenAI chat-completions shape, so the loop,
tools and validator are identical whichever model runs. Open models are less strict about tool
calls, so parsing is lenient: nested JSON passed as strings is decoded, malformed arguments
are handed back for the validator to reject, and Groq's `tool_use_failed` errors are retried.
"""

import json
import uuid
from types import SimpleNamespace
from typing import Any

from app.agent.llm import ModelTurn, Usage
from app.core.logging import get_logger

log = get_logger("gabriella.llm")

FINISH_REASONS = {
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "refusal",
}
MAX_TOOL_FORMAT_RETRIES = 2


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def _attr(block: Any, name: str, default: Any = None) -> Any:
    return block.get(name, default) if isinstance(block, dict) else getattr(block, name, default)


def to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for msg in messages:
        role, content = msg["role"], msg["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text = " ".join(
                _attr(b, "text", "") for b in content if _attr(b, "type") == "text"
            ).strip()
            calls = [
                {
                    "id": _attr(b, "id"),
                    "type": "function",
                    "function": {
                        "name": _attr(b, "name"),
                        "arguments": json.dumps(_attr(b, "input") or {}),
                    },
                }
                for b in content
                if _attr(b, "type") == "tool_use"
            ]
            entry: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
            continue
        # A user turn carrying tool results becomes one `tool` message per result.
        texts = []
        for b in content:
            if _attr(b, "type") == "tool_result":
                body = _attr(b, "content", "")
                if _attr(b, "is_error"):
                    body = f"ERROR: {body}"
                out.append(
                    {"role": "tool", "tool_call_id": _attr(b, "tool_use_id"), "content": str(body)}
                )
            elif _attr(b, "type") == "text":
                texts.append(_attr(b, "text", ""))
        if texts:
            out.append({"role": "user", "content": "\n".join(texts)})
    return out


def _decode_nested(value: Any) -> Any:
    """Smaller models often send nested objects as JSON strings: {"filters": "{...}"}."""
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return _decode_nested(json.loads(value))
        except ValueError:
            return value
    if isinstance(value, dict):
        return {k: _decode_nested(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_nested(v) for v in value]
    return value


def parse_arguments(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        # Hand the bad payload on; the tool or validator rejects it and the model can retry.
        return {"_unparseable_arguments": raw[:500]}
    parsed = _decode_nested(parsed)
    return parsed if isinstance(parsed, dict) else {"_unparseable_arguments": raw[:500]}


def from_openai_response(response: Any) -> ModelTurn:
    choice = response.choices[0]
    message = choice.message
    blocks: list[Any] = []
    if message.content:
        blocks.append(SimpleNamespace(type="text", text=message.content))
    for call in message.tool_calls or []:
        blocks.append(
            SimpleNamespace(
                type="tool_use",
                id=call.id or f"call_{uuid.uuid4().hex[:12]}",
                name=call.function.name,
                input=parse_arguments(call.function.arguments),
            )
        )
    stop = FINISH_REASONS.get(choice.finish_reason or "", "end_turn")
    if stop == "end_turn" and message.tool_calls:
        stop = "tool_use"  # some servers report "stop" alongside tool calls
    usage = response.usage
    details = getattr(usage, "prompt_tokens_details", None) if usage else None
    return ModelTurn(
        content=blocks,
        stop_reason=stop,
        usage=Usage(
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cache_read_tokens=getattr(details, "cached_tokens", 0) or 0,
        ),
        model=getattr(response, "model", None),
    )


class OpenAICompatibleBackend:
    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        timeout: float = 120.0,
    ) -> None:
        from openai import AsyncOpenAI

        self.provider = provider
        self.model = model
        self.name = f"{provider}:{model}"
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout, max_retries=2
        )

    async def complete(
        self, *, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> ModelTurn:
        import openai

        request = {
            "model": self.model,
            "messages": to_openai_messages(system, messages),
            "tools": to_openai_tools(tools),
            "tool_choice": "auto",
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        for attempt in range(MAX_TOOL_FORMAT_RETRIES + 1):
            try:
                return from_openai_response(await self._client.chat.completions.create(**request))
            except openai.BadRequestError as exc:
                # Groq rejects generations whose tool call it can't parse; a fresh sample usually works.
                if "tool_use_failed" not in str(exc) or attempt == MAX_TOOL_FORMAT_RETRIES:
                    raise
                log.warning("tool_call_format_retry", provider=self.provider, attempt=attempt + 1)
        raise RuntimeError("unreachable")
