"""Model backends.

`AnthropicBackend` calls Claude with streaming (so long turns never hit HTTP timeouts),
adaptive thinking, an explicit effort level, prompt caching on the static tools + system prefix,
and server-side refusal fallbacks. `ScriptedBackend` replays canned responses for tests.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from types import SimpleNamespace
from typing import Any, Protocol

from app.core.config import get_settings


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class ModelTurn:
    content: list[Any]  # SDK content blocks (or look-alikes in tests); resent unchanged
    stop_reason: str | None
    usage: Usage = field(default_factory=Usage)
    model: str | None = None


class ModelBackend(Protocol):
    name: str

    async def complete(
        self, *, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> ModelTurn: ...


class AnthropicBackend:
    def __init__(self, *, api_key: str, model: str, effort: str, max_tokens: int = 8000) -> None:
        import anthropic

        self.name = model
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=120.0, max_retries=2)

    async def complete(
        self, *, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> ModelTurn:
        async with self._client.beta.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            # The system prompt is static; caching it also caches the tool definitions before it.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": self._effort},
            # Policy declines are retried server-side on a fallback model in the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            message = await stream.get_final_message()
        usage = message.usage
        return ModelTurn(
            content=list(message.content),
            stop_reason=message.stop_reason,
            usage=Usage(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            ),
            model=message.model,
        )


def block(**fields: Any) -> SimpleNamespace:
    """A content-block look-alike for scripted responses."""
    return SimpleNamespace(**fields)


def tool_use(name: str, input: dict[str, Any], id: str | None = None) -> SimpleNamespace:  # noqa: A002
    return block(
        type="tool_use",
        id=id or f"toolu_{name}_{abs(hash(str(input))) % 10**8}",
        name=name,
        input=input,
    )


class ScriptedBackend:
    """Replays a fixed sequence of turns; each item may be a ModelTurn or a callable(messages)."""

    name = "scripted"

    def __init__(self, turns: Iterable[Any]) -> None:
        self._turns = list(turns)
        self.requests: list[list[dict[str, Any]]] = []

    async def complete(
        self, *, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> ModelTurn:
        self.requests.append(list(messages))
        if not self._turns:
            raise RuntimeError("ScriptedBackend ran out of turns")
        turn = self._turns.pop(0)
        return turn(messages) if callable(turn) else turn


def _secret(value: Any) -> str:
    return value.get_secret_value() if value is not None else ""


def resolve_provider() -> str:
    """Which model provider to use. `auto` picks the first one with a key configured; Ollama
    needs no key, so it is used only when chosen explicitly (LLM_PROVIDER=ollama)."""
    settings = get_settings()
    if settings.llm_provider != "auto":
        return settings.llm_provider
    if _secret(settings.groq_api_key):
        return "groq"
    if _secret(settings.anthropic_api_key):
        return "anthropic"
    return "none"


@lru_cache
def default_backend() -> ModelBackend | None:
    """The configured model backend, or None to use the deterministic stylist."""
    from app.agent.openai_compat import OpenAICompatibleBackend

    settings = get_settings()
    provider = resolve_provider()
    if provider == "groq" and _secret(settings.groq_api_key):
        return OpenAICompatibleBackend(
            provider="groq",
            base_url=settings.groq_base_url,
            api_key=_secret(settings.groq_api_key),
            model=settings.groq_model,
        )
    if provider == "ollama":
        # Local models are slower on CPU or small GPUs; give them more time per request.
        return OpenAICompatibleBackend(
            provider="ollama",
            base_url=settings.ollama_base_url,
            api_key="ollama",
            model=settings.ollama_model,
            timeout=300.0,
        )
    if provider == "openai_compatible" and settings.llm_base_url:
        return OpenAICompatibleBackend(
            provider="openai_compatible",
            base_url=settings.llm_base_url,
            api_key=_secret(settings.llm_api_key) or "none",
            model=settings.llm_model,
        )
    if provider == "anthropic" and _secret(settings.anthropic_api_key):
        return AnthropicBackend(
            api_key=_secret(settings.anthropic_api_key),
            model=settings.gabriella_model,
            effort=settings.gabriella_effort,
        )
    return None
