"""The Claude tool-use loop for one shopper turn.

Within a turn the history is append-only: each assistant response goes back unchanged (thinking
blocks included) followed by one user message carrying every tool result. The turn ends when
`present_recommendation` passes server-side validation, or after MAX_FIX_ATTEMPTS failed
validations, at which point `repair` makes the answer safe to display.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.llm import ModelBackend, Usage
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.schemas import Recommendation
from app.agent.tools import TOOL_DEFINITIONS, ToolContext, execute_tool
from app.agent.validator import owned_product_ids, repair, validate
from app.core.logging import get_logger

log = get_logger("gabriella.agent")

MAX_MODEL_REQUESTS = 10
MAX_FIX_ATTEMPTS = 2

Emit = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class TurnResult:
    recommendation: Recommendation
    validation: dict[str, Any] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    model_requests: int = 0
    model: str | None = None
    error: str | None = None
    # True when the answer came through a validated present_recommendation call.
    presented: bool = False


def status_text(name: str, args: dict[str, Any], ctx: ToolContext) -> str:
    where = f" at {ctx.store.city}" if ctx.store else ""
    if name == "search_catalogue":
        filters = args.get("filters") or {}
        what = (
            ", ".join(c.replace("-", " ") for c in filters.get("categories", []))
            or args.get("query")
            or "the catalogue"
        )
        size = f" in {filters['size']}" if filters.get("size") else ""
        return f"Searching {what}{size}{where}…"
    return {
        "get_product": "Reading the product details…",
        "find_similar_products": f"Finding similar pieces{where}…",
        "check_variant_inventory": f"Checking stock{where}…",
        "present_recommendation": "Checking every piece against live stock…",
    }.get(name, "Working…")


def _text_of(content: list[Any]) -> str:
    return " ".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


async def run_llm_turn(
    backend: ModelBackend,
    ctx: ToolContext,
    history: list[dict[str, Any]],
    user_content: str,
    emit: Emit,
    *,
    system: str = SYSTEM_PROMPT,
    tools: list[dict[str, Any]] | None = None,
    max_requests: int = MAX_MODEL_REQUESTS,
    max_fix_attempts: int = MAX_FIX_ATTEMPTS,
) -> TurnResult:
    tools = TOOL_DEFINITIONS if tools is None else tools
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": user_content}]
    usage = Usage()
    requests = 0
    fix_attempts = 0
    nudged = False
    validation: dict[str, Any] = {"attempts": 0, "problems": [], "repairs": []}
    model_name: str | None = None

    while requests < max_requests:
        turn = await backend.complete(system=system, tools=tools, messages=messages)
        requests += 1
        model_name = turn.model or backend.name
        usage.input_tokens += turn.usage.input_tokens
        usage.output_tokens += turn.usage.output_tokens
        usage.cache_read_tokens += turn.usage.cache_read_tokens

        if turn.stop_reason == "refusal":
            return TurnResult(
                Recommendation(
                    message="I can only help with clothing and styling from our store. "
                    "What are you shopping for today?"
                ),
                validation,
                usage,
                requests,
                model_name,
                error="refusal",
            )

        tool_uses = [b for b in turn.content if getattr(b, "type", None) == "tool_use"]
        messages.append({"role": "assistant", "content": turn.content})

        if turn.stop_reason == "max_tokens" and tool_uses:
            # A truncated tool input parses as a partial object; never run it.
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": b.id,
                            "is_error": True,
                            "content": "Your tool input was cut off. Retry with a shorter call.",
                        }
                        for b in tool_uses
                    ],
                }
            )
            continue

        if not tool_uses:
            text = _text_of(turn.content)
            if not nudged:
                # Every answer must go through present_recommendation so it can be validated.
                nudged = True
                messages.append(
                    {
                        "role": "user",
                        "content": "Please deliver that answer by calling present_recommendation.",
                    }
                )
                continue
            return TurnResult(
                Recommendation(
                    message=text[:1200] or "Could you tell me a bit more about what you're after?"
                ),
                validation,
                usage,
                requests,
                model_name,
            )

        final: Recommendation | None = None
        results: list[dict[str, Any]] = []
        # Run lookups first so a same-step present_recommendation can use what they return.
        for block in sorted(tool_uses, key=lambda b: b.name == "present_recommendation"):
            await emit(
                {
                    "type": "status",
                    "text": status_text(
                        block.name, block.input if isinstance(block.input, dict) else {}, ctx
                    ),
                }
            )
            if block.name != "present_recommendation":
                content, is_error = await execute_tool(ctx, block.name, block.input)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                        "is_error": is_error,
                    }
                )
                continue

            report = await validate(
                ctx.session, block.input, store=ctx.store, seen_product_ids=ctx.seen_product_ids
            )
            validation["attempts"] += 1
            validation["checked_items"] = report.checked_items
            ctx.calls.append(
                {"name": "present_recommendation", "ok": report.ok, "problems": report.problems}
            )
            if report.ok:
                final = report.recommendation
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Shown to the shopper.",
                    }
                )
            elif report.recommendation is not None and fix_attempts >= max_fix_attempts:
                final, notes = await repair(
                    ctx.session, report, store=ctx.store, avoid=owned_product_ids(ctx.profile)
                )
                validation["repairs"] = notes
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Shown after server-side corrections.",
                    }
                )
            else:
                fix_attempts += 1
                validation["problems"].extend(report.problems)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "is_error": True,
                        "content": json.dumps(
                            {
                                "error": "Not shown yet. Fix these problems and call present_recommendation again.",
                                "problems": report.problems,
                                "hint": "Use only products and variant IDs your tools returned, in the shopper's sizes, in stock at their store.",
                            }
                        ),
                    }
                )

        messages.append({"role": "user", "content": results})
        if final is not None:
            validation["passed_first_time"] = (
                validation["attempts"] == 1 and not validation["repairs"]
            )
            return TurnResult(final, validation, usage, requests, model_name, presented=True)

    log.warning("agent_step_limit", requests=requests)
    return TurnResult(
        Recommendation(
            message="Sorry, I couldn't put that together just now. Could you try rephrasing?"
        ),
        validation,
        usage,
        requests,
        model_name,
        error="step_limit",
    )
