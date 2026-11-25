"""Pipeline mode: deterministic retrieval and composition, then one model call for judgement.

This follows the original design brief to the letter and is built for metered, free-tier or
small models (Groq's free tier allows 8,000 tokens a minute; Ollama on a laptop GPU is slow):

1. The rule-based stylist parses constraints, runs hybrid search under hard SQL filters
   (category, size, stock at the store, budget) and composes a validated draft outfit,
   keeping a shortlist of in-stock alternatives for every slot.
2. The model sees only that draft and shortlist, as compact facts, and makes one
   `present_recommendation` call: keep or swap pieces, write the message and reasons, ask a
   clarifying question, or steer an off-topic request back.
3. The same server-side validator checks the answer. If the model fails, is rate limited or
   offline, the shopper gets the validated draft instead.

About 2,000 tokens a turn, against 10,000-28,000 for the open-ended tool loop.
"""

import json
import re
from typing import Any

from app.agent.fallback import _RESET, run_fallback_turn
from app.agent.llm import ModelBackend
from app.agent.loop import Emit, TurnResult, run_llm_turn
from app.agent.schemas import Recommendation, SessionConstraints
from app.agent.tools import TOOL_DEFINITIONS, ToolContext, compact_products
from app.agent.validator import owned_product_ids, repair, validate
from app.core.logging import get_logger

log = get_logger("gabriella.pipeline")

PRESENT_TOOL = [t for t in TOOL_DEFINITIONS if t["name"] == "present_recommendation"]
MAX_CANDIDATES_PER_SLOT = 4

PIPELINE_SYSTEM_PROMPT = """\
You are Gabriella, the in-store style advisor for a multi-brand Indian clothing retailer. \
You talk like a skilled, warm salesperson: concise, confident, honest about what is on the shelves.

Each turn, the store's styling engine has already searched live stock for you. You receive:
- <draft>: an answer it composed (it may be a question, an outfit, or a list of picks);
- <candidates>: other in-stock pieces in the shopper's sizes, grouped by outfit slot.

Your job: improve the draft, then call present_recommendation exactly once.
- Use only product IDs from <draft> or <candidates>. Never invent products, prices, sizes or stock.
- Keep the draft's pieces when they work; swap a piece for a candidate when it suits the \
occasion, colours or budget better. Keep any outfit within the shopper's budget.
- Write a short message (1-3 sentences, no product lists or prices: the cards show those) and \
one factual reason per item (colour pairing, formality, fabric, occasion).
- If the draft asks a question, ask it in your own words with helpful follow_ups and empty groups.
- If nothing fits, say so plainly and suggest how to adjust (budget, store, size). If the draft says what the cheapest complete look costs, keep that figure: it is the most useful fact you have.
- If the request is not about clothing from this store, reply briefly with empty groups and steer back.
- Keep `constraints` complete: copy the known ones and add anything new the shopper said.
- Never comment on body shape, race, gender identity or other personal attributes.
Indian rupees, written like ₹2,499.
"""


def _slim(product: dict[str, Any]) -> dict[str, Any]:
    """Just enough for styling judgement; the validator pins exact sizes, so no variant IDs."""
    return {
        "id": product["product_id"],
        "name": product["name"],
        "category": product["category"],
        "gender": product["gender"],
        "colour": product["colour"],
        "material": product["material"],
        "fit": product["fit"],
        "formality": product["formality"],
        "price": product["price"],
        "sizes": [s["size"] for s in product["in_stock_sizes"]],
    }


async def _briefing(ctx: ToolContext, draft: Recommendation) -> str:
    draft_ids = [i.product_id for g in draft.groups for i in g.items]
    extra = {
        slot: [pid for pid in ids if pid not in draft_ids][:MAX_CANDIDATES_PER_SLOT]
        for slot, ids in ctx.shortlists.items()
    }
    all_ids = list(dict.fromkeys(draft_ids + [pid for ids in extra.values() for pid in ids]))
    facts = {
        p["product_id"]: _slim(p) for p in await compact_products(ctx.session, all_ids, ctx.store)
    }
    draft_view = {
        "message": draft.message,
        "groups": [
            {
                "title": g.title,
                "kind": g.kind,
                "items": [
                    {"role": i.role, **facts[i.product_id]}
                    for i in g.items
                    if i.product_id in facts
                ],
            }
            for g in draft.groups
        ],
        "follow_ups": draft.follow_ups,
        "constraints": draft.constraints.model_dump(exclude_none=True, exclude_defaults=True),
    }
    candidates = {
        slot: [facts[pid] for pid in ids if pid in facts] for slot, ids in extra.items() if ids
    }
    compact = {"separators": (",", ":"), "ensure_ascii": False}
    return (
        f"<draft>{json.dumps(draft_view, **compact)}</draft>\n"
        f"<candidates>{json.dumps(candidates, **compact)}</candidates>"
    )


def _merge_constraints(draft: SessionConstraints, model: SessionConstraints) -> SessionConstraints:
    """The parser's constraints are the floor; the model may add to them or refine them."""
    merged = draft.model_dump()
    for key, value in model.model_dump().items():
        if value not in (None, [], ""):
            merged[key] = value
    return SessionConstraints.model_validate(merged)


_CHEAPEST = re.compile(r"The most affordable complete look here comes to about (₹[\d,]+)\.")


def _keep_cheapest_look(draft_message: str, message: str) -> str:
    """Models often soften "it costs at least ₹7,097" into "consider raising the budget".
    The real figure is the most useful fact in that answer, so put it back if it was dropped."""
    found = _CHEAPEST.search(draft_message)
    if found and found.group(1) not in message:
        return f"{message.rstrip()} {found.group(0)}"
    return message


async def run_pipeline_turn(
    backend: ModelBackend,
    ctx: ToolContext,
    constraints: dict[str, Any],
    focus_id: int | None,
    history: list[dict[str, Any]],
    preamble: str,
    text: str,
    emit: Emit,
) -> TurnResult:
    draft_result = await run_fallback_turn(ctx, constraints, focus_id, text, emit)
    if _RESET.search(text):
        # "Start fresh" clears everything; a model would only drag the old context back in.
        draft_result.validation["strategy"] = "pipeline-reset"
        return draft_result
    draft = draft_result.recommendation
    briefing = await _briefing(ctx, draft)
    await emit({"type": "status", "text": "Gabriella is choosing the best combination…"})
    try:
        result = await run_llm_turn(
            backend,
            ctx,
            history,
            f"{preamble}{text}\n\n{briefing}",
            emit,
            system=PIPELINE_SYSTEM_PROMPT,
            tools=PRESENT_TOOL,
            max_requests=3,
            max_fix_attempts=1,
        )
    except Exception as exc:  # noqa: BLE001 - rate limited or offline: the draft is already valid
        log.warning("pipeline_model_failed", error=f"{type(exc).__name__}: {exc}"[:300])
        draft_result.error = f"{type(exc).__name__}: {exc}"[:500]
        draft_result.validation["strategy"] = "pipeline-draft"
        return draft_result

    if result.error or not result.presented:
        # No validated answer from the model (refusal, step limit, plain text): use the draft.
        draft_result.error = result.error or "model did not call present_recommendation"
        draft_result.validation["strategy"] = "pipeline-draft"
        return draft_result
    message = _keep_cheapest_look(draft.message, result.recommendation.message)
    merged = result.recommendation.model_copy(
        update={
            "message": message,
            "constraints": _merge_constraints(draft.constraints, result.recommendation.constraints),
        }
    )
    # Re-check with the merged constraints, so the shopper's sizes and budget always apply
    # even if the model dropped them from its own copy.
    report = await validate(
        ctx.session, merged.model_dump(), store=ctx.store, seen_product_ids=ctx.seen_product_ids
    )
    if report.ok:
        result.recommendation = report.recommendation
    else:
        result.recommendation, notes = await repair(
            ctx.session, report, store=ctx.store, avoid=owned_product_ids(ctx.profile)
        )
        result.validation.setdefault("repairs", []).extend(notes)
    if report.reasons_rewritten:
        result.validation["reasons_rewritten"] = report.reasons_rewritten
    result.validation["strategy"] = "pipeline"
    result.validation["draft_items"] = sum(len(g.items) for g in draft.groups)
    return result
