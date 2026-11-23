"""Gabriella's grounding guarantees: validator, Claude tool loop (scripted), fallback agent."""

import json
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.fallback import update_constraints
from app.agent.llm import ModelTurn, ScriptedBackend, Usage, block, tool_use
from app.agent.loop import run_llm_turn
from app.agent.schemas import SessionConstraints
from app.agent.tools import ToolContext, execute_tool
from app.agent.validator import repair, validate
from app.db.models import Store
from tests.conftest import Catalogue
from tests.factories import add_product


async def _ctx(session: AsyncSession, store_code: str | None = "PUN") -> ToolContext:
    stores = {s.code: s for s in (await session.scalars(select(Store))).all()}
    return ToolContext(
        session=session, store=stores.get(store_code) if store_code else None, stores=stores
    )


def _rec(
    items: list[dict[str, Any]], *, kind: str = "outfit", **constraints: Any
) -> dict[str, Any]:
    return {
        "message": "Here you go.",
        "groups": [{"title": "Look", "kind": kind, "items": items}],
        "constraints": constraints,
        "follow_ups": [],
    }


async def _noop(event: dict[str, Any]) -> None:
    return None


# ------------------------------------------------------------------ validator


async def test_validator_accepts_grounded_items_and_pins_size(
    session: AsyncSession, catalogue: Catalogue
):
    ctx = await _ctx(session)
    raw = _rec(
        [{"product_id": catalogue.navy_shirt, "role": "top", "reason": "Navy works"}],
        apparel_size="M",
    )
    report = await validate(session, raw, store=ctx.store, seen_product_ids={catalogue.navy_shirt})
    assert report.ok, report.problems
    item = report.recommendation.groups[0].items[0]
    assert (
        item.variant_id == catalogue.variants["navy-linen-shirt:M"]
    )  # pinned to the shopper's size


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("unknown", "does not exist"),
        ("unseen", "was not returned by any tool"),
        ("retired", "discontinued"),
        ("sold_out_variant", "out of stock"),
        ("wrong_size_variant", "the shopper wears"),
        ("size_unavailable", "not in stock in size M"),
        ("foreign_variant", "does not belong"),
    ],
)
async def test_validator_rejects_ungrounded_items(
    session: AsyncSession, catalogue: Catalogue, case: str, expected: str
):
    ctx = await _ctx(session)
    v = catalogue.variants
    seen = {
        catalogue.navy_shirt,
        catalogue.beige_chinos,
        catalogue.retired_tee,
        catalogue.white_sneakers,
    }
    items, constraints = {
        "unknown": ([{"product_id": 999_999, "role": "top", "reason": ""}], {}),
        "unseen": (
            [{"product_id": catalogue.white_sneakers, "role": "footwear", "reason": ""}],
            {},
        ),
        "retired": ([{"product_id": catalogue.retired_tee, "role": "top", "reason": ""}], {}),
        "sold_out_variant": (
            [
                {
                    "product_id": catalogue.beige_chinos,
                    "variant_id": v["beige-chinos:M"],
                    "role": "bottom",
                    "reason": "",
                }
            ],
            {},
        ),
        "wrong_size_variant": (
            [
                {
                    "product_id": catalogue.beige_chinos,
                    "variant_id": v["beige-chinos:L"],
                    "role": "bottom",
                    "reason": "",
                }
            ],
            {"apparel_size": "M"},
        ),
        "size_unavailable": (
            [{"product_id": catalogue.beige_chinos, "role": "bottom", "reason": ""}],
            {"apparel_size": "M"},
        ),
        "foreign_variant": (
            [
                {
                    "product_id": catalogue.navy_shirt,
                    "variant_id": v["beige-chinos:L"],
                    "role": "top",
                    "reason": "",
                }
            ],
            {},
        ),
    }[case]
    if case == "unseen":
        seen = seen - {catalogue.white_sneakers}
    report = await validate(
        session, _rec(items, **constraints), store=ctx.store, seen_product_ids=seen
    )
    assert not report.ok
    assert any(expected in p for p in report.problems), report.problems


async def test_validator_enforces_outfit_budget(session: AsyncSession, catalogue: Catalogue):
    ctx = await _ctx(session)
    raw = _rec(
        [
            {"product_id": catalogue.navy_shirt, "role": "top", "reason": ""},
            {"product_id": catalogue.beige_chinos, "role": "bottom", "reason": ""},
        ],
        budget_max=4000,
    )
    report = await validate(
        session,
        raw,
        store=ctx.store,
        seen_product_ids={catalogue.navy_shirt, catalogue.beige_chinos},
    )
    assert any("over the ₹4,000 budget" in p for p in report.problems)

    fixed, notes = await repair(session, report, store=ctx.store)
    total = sum(
        {catalogue.navy_shirt: 1999, catalogue.beige_chinos: 2499}[i.product_id]
        for g in fixed.groups
        for i in g.items
    )
    assert total <= 4000 and notes


async def test_repair_swaps_sold_out_items_for_in_stock_alternatives(
    session: AsyncSession, catalogue: Catalogue
):
    stone = await add_product(
        session,
        slug="stone-chinos",
        name="Relaxed Chinos",
        category="chinos",
        colour="Stone",
        price=2299,
        stock={catalogue.pune: {"M": 2}},
    )
    ctx = await _ctx(session)
    raw = _rec(
        [{"product_id": catalogue.beige_chinos, "role": "bottom", "reason": ""}], apparel_size="M"
    )
    report = await validate(
        session, raw, store=ctx.store, seen_product_ids={catalogue.beige_chinos}
    )
    assert not report.ok
    fixed, notes = await repair(session, report, store=ctx.store)
    (item,) = fixed.groups[0].items
    assert item.product_id == stone.id and item.variant_id is not None
    assert "Swapped in" in item.reason


# ------------------------------------------------------------------ tools


async def test_search_tool_returns_only_in_stock_sizes_and_records_grounding(
    session: AsyncSession, catalogue: Catalogue
):
    ctx = await _ctx(session)
    content, is_error = await execute_tool(
        ctx, "search_catalogue", {"query": "chinos", "filters": {"categories": ["chinos"]}}
    )
    assert not is_error
    (product,) = json.loads(content)["products"]
    assert product["product_id"] == catalogue.beige_chinos
    assert [s["size"] for s in product["in_stock_sizes"]] == ["L"]  # M is sold out in Pune
    assert catalogue.beige_chinos in ctx.seen_product_ids

    content, is_error = await execute_tool(
        ctx,
        "search_catalogue",
        {"query": "chinos", "filters": {"size": "m", "categories": ["chinos"]}},
    )
    assert json.loads(content)["products"] == []

    content, is_error = await execute_tool(
        ctx, "search_catalogue", {"query": "x", "filters": {"store_code": "XYZ"}}
    )
    assert is_error and "Unknown store code" in content
    content, is_error = await execute_tool(ctx, "get_product", {"product_id": "abc"})
    assert is_error and "Invalid input" in content
    assert [c["ok"] for c in ctx.calls] == [True, True, False, False]


async def test_inventory_tool_reports_other_stores(session: AsyncSession, catalogue: Catalogue):
    ctx = await _ctx(session)
    content, _ = await execute_tool(
        ctx, "check_variant_inventory", {"variant_id": catalogue.variants["beige-chinos:M"]}
    )
    body = json.loads(content)
    assert body["in_stock_at_store"] is False and body["other_stores"] == {"BOM": 4}


# ------------------------------------------------------------------ Claude loop (scripted)


def _final(*blocks: Any) -> ModelTurn:
    return ModelTurn(
        content=list(blocks),
        stop_reason="tool_use",
        usage=Usage(input_tokens=100, output_tokens=20, cache_read_tokens=80),
    )


async def test_llm_loop_happy_path(session: AsyncSession, catalogue: Catalogue):
    ctx = await _ctx(session)
    search = tool_use(
        "search_catalogue",
        {"query": "linen shirt", "filters": {"categories": ["casual-shirts"]}},
        id="t1",
    )
    present = tool_use(
        "present_recommendation",
        _rec(
            [
                {
                    "product_id": catalogue.navy_shirt,
                    "role": "top",
                    "reason": "Navy linen for dinner",
                }
            ],
            apparel_size="M",
        ),
        id="t2",
    )
    backend = ScriptedBackend(
        [_final(block(type="text", text="Let me look."), search), _final(present)]
    )
    events: list[dict[str, Any]] = []

    async def emit(e: dict[str, Any]) -> None:
        events.append(e)

    result = await run_llm_turn(backend, ctx, [], "A shirt for dinner, size M", emit)
    assert result.validation["passed_first_time"] is True
    assert (
        result.recommendation.groups[0].items[0].variant_id
        == catalogue.variants["navy-linen-shirt:M"]
    )
    assert result.model_requests == 2 and result.usage.cache_read_tokens == 160
    # The second request carries the assistant turn unchanged, then the matching tool_result.
    second = backend.requests[1]
    assert second[-2]["role"] == "assistant" and second[-2]["content"][1].id == "t1"
    assert second[-1]["content"][0]["tool_use_id"] == "t1"
    assert any("Searching casual shirts" in e["text"] for e in events)


async def test_llm_loop_rejects_hallucinations_then_accepts_fix(
    session: AsyncSession, catalogue: Catalogue
):
    ctx = await _ctx(session)
    search = tool_use("search_catalogue", {"query": "shirt"}, id="t1")
    bad = tool_use(
        "present_recommendation",
        _rec([{"product_id": 424242, "role": "top", "reason": "Invented"}]),
        id="t2",
    )
    good = tool_use(
        "present_recommendation",
        _rec([{"product_id": catalogue.navy_shirt, "role": "top", "reason": "Real"}]),
        id="t3",
    )
    backend = ScriptedBackend([_final(search), _final(bad), _final(good)])
    result = await run_llm_turn(backend, ctx, [], "a shirt", _noop)
    assert [i.product_id for i in result.recommendation.groups[0].items] == [catalogue.navy_shirt]
    assert result.validation["attempts"] == 2 and result.validation["passed_first_time"] is False
    error_result = backend.requests[2][-1]["content"][0]
    assert error_result["is_error"] is True and "does not exist" in error_result["content"]


async def test_llm_loop_repairs_after_repeated_failures(
    session: AsyncSession, catalogue: Catalogue
):
    ctx = await _ctx(session)
    ctx.seen_product_ids.add(catalogue.beige_chinos)
    sold_out = _rec(
        [{"product_id": catalogue.beige_chinos, "role": "bottom", "reason": ""}], apparel_size="M"
    )
    backend = ScriptedBackend(
        [_final(tool_use("present_recommendation", sold_out, id=f"t{i}")) for i in range(3)]
    )
    result = await run_llm_turn(backend, ctx, [], "chinos in M", _noop)
    # No in-stock alternative exists in the fixture, so the item is dropped rather than shown.
    assert result.recommendation.groups == []
    assert result.validation["repairs"] == [f"dropped {catalogue.beige_chinos}"]


async def test_llm_loop_requires_present_recommendation(
    session: AsyncSession, catalogue: Catalogue
):
    ctx = await _ctx(session)
    text_only = ModelTurn(
        content=[block(type="text", text="Navy goes with beige!")], stop_reason="end_turn"
    )
    present = tool_use("present_recommendation", {**_rec([]), "groups": []}, id="t1")
    backend = ScriptedBackend([text_only, _final(present)])
    result = await run_llm_turn(backend, ctx, [], "hi", _noop)
    assert result.model_requests == 2
    assert "present_recommendation" in backend.requests[1][-1]["content"]


async def test_llm_loop_handles_refusal(session: AsyncSession, catalogue: Catalogue):
    ctx = await _ctx(session)
    backend = ScriptedBackend([ModelTurn(content=[], stop_reason="refusal")])
    result = await run_llm_turn(backend, ctx, [], "something off-topic", _noop)
    assert result.error == "refusal" and result.recommendation.groups == []


# ------------------------------------------------------------------ fallback constraints


def test_constraint_updates_carry_and_refine():
    c = update_constraints(
        SessionConstraints(), "casual dinner under ₹5,000 for men, I wear M and UK 9"
    )
    assert (c.occasion, c.budget_max, c.gender, c.apparel_size, c.footwear_size, c.formality) == (
        "dinner",
        5000,
        "men",
        "M",
        "UK 9",
        "relaxed",
    )
    c = update_constraints(c, "make it more formal")
    assert c.formality == "smart" and c.budget_max == 5000
    c = update_constraints(c, "something for a wedding instead")
    assert c.occasion == "wedding" and c.formality is None  # new occasion, new dress code
    assert update_constraints(c, "let's start fresh") == SessionConstraints()
