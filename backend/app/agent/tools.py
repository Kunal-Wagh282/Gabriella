"""Gabriella's tools: thin, typed wrappers over the catalogue, retrieval and inventory services.

Tool results are compact JSON with only the facts the model needs. Every product a tool
returns is recorded in `ToolContext.seen_product_ids`; the validator rejects any product
the model recommends without having retrieved it.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.schemas import (
    CheckInventoryInput,
    FindSimilarInput,
    GetProductInput,
    SearchCatalogueInput,
    SearchFilters,
)
from app.core.errors import AppError
from app.db.models import Inventory, Product, ProductVariant, Store
from app.retrieval.search import hybrid_search
from app.retrieval.similar import find_similar
from app.schemas.catalogue import ProductFilters
from app.services.inventory import variant_availability

CATEGORY_SLUGS = (
    "Groups: tops, bottoms, dresses, outerwear, ethnic, footwear, accessories. "
    "Leaves: t-shirts, polos, casual-shirts, formal-shirts, blouses-tops, knitwear, "
    "hoodies-sweatshirts, chinos, jeans, trousers, shorts, joggers, skirts, day-evening-dresses, "
    "blazers, jackets, kurtas, nehru-jackets, ethnic-bottoms, sneakers, loafers, formal-shoes, "
    "boots, heels-flats, sandals, juttis, belts, bags, caps, scarves-stoles."
)
STORE_CODES = (
    "PUN (Pune), BOM (Mumbai), BLR (Bengaluru), DEL (New Delhi), HYD (Hyderabad), WEB (online)"
)

_FILTERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "categories": {
            "type": "array",
            "items": {"type": "string"},
            "description": f"Category slugs. {CATEGORY_SLUGS}",
        },
        "colours": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Colour names (navy, beige) or families (blue, neutral, green).",
        },
        "gender": {
            "type": "string",
            "enum": ["men", "women", "unisex"],
            "description": "Unisex items are always included for men or women.",
        },
        "size": {
            "type": "string",
            "description": "Only products with this size in stock: XS-XXL for apparel, 'UK 9' for shoes.",
        },
        "min_price": {"type": "integer"},
        "max_price": {"type": "integer", "description": "Per item, in rupees."},
        "occasion": {
            "type": "string",
            "description": "Soft ranking signal, e.g. office, wedding, dinner.",
        },
        "style": {
            "type": "string",
            "description": "Soft ranking signal, e.g. smart casual, minimal.",
        },
        "store_code": {
            "type": "string",
            "description": f"Check stock at another store: {STORE_CODES}. Defaults to the shopper's store.",
        },
        "include_out_of_stock": {
            "type": "boolean",
            "description": "Default false: only what can be bought now.",
        },
    },
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_catalogue",
        "description": (
            "Search the live catalogue. Hard filters apply first in the database (category, colour, "
            "gender, size, price, stock at the shopper's store), then results are ranked by text and "
            "visual similarity to `query`. Returns products with their in-stock sizes and variant IDs. "
            "Call once per outfit slot when building a look."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Descriptive words: style, colour, fabric, mood.",
                },
                "filters": _FILTERS_SCHEMA,
                "limit": {"type": "integer", "description": "1-12, default 8."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_product",
        "description": "Full details for one product: description, every size with its variant ID, and stock at every store.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"product_id": {"type": "integer"}},
            "required": ["product_id"],
        },
    },
    {
        "name": "find_similar_products",
        "description": (
            "Alternatives to a product (same garment type, different style), ranked by look and "
            "description, with reasons. Use for 'something like this', or when a size is sold out."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "product_id": {"type": "integer"},
                "filters": _FILTERS_SCHEMA,
                "limit": {"type": "integer", "description": "1-10, default 6."},
            },
            "required": ["product_id"],
        },
    },
    {
        "name": "check_variant_inventory",
        "description": "Exact stock for one variant (a product in one size) at a store and at every other store.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "variant_id": {"type": "integer"},
                "store_code": {
                    "type": "string",
                    "description": f"{STORE_CODES}. Defaults to the shopper's store.",
                },
            },
            "required": ["variant_id"],
        },
    },
    {
        "name": "build_outfit",
        "description": (
            "Compose a complete in-stock outfit (top, bottom, shoes, optional accessory) with the "
            "store's deterministic stylist: colour harmony, formality, occasion and the whole budget. "
            "Optionally around a seed product. Returns the outfit plus in-stock alternatives per slot."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "seed_product_id": {"type": "integer", "description": "Build around this product."},
                "occasion": {"type": "string"},
                "budget_max": {"type": "integer", "description": "Whole outfit, rupees."},
                "gender": {"type": "string", "enum": ["men", "women"]},
                "apparel_size": {"type": "string"},
                "footwear_size": {"type": "string"},
                "formality": {"type": "string", "enum": ["relaxed", "smart", "formal"]},
                "colours": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "present_recommendation",
        "description": (
            "Deliver your answer to the shopper. Always finish every turn by calling this exactly once, "
            "even when you only have a question or no products to show (use empty groups). Products "
            "are shown as cards built from the database, so reference them only by product_id "
            "(and variant_id once the size is known). The server checks every item against live stock; "
            "if it reports problems, fix them and call this again."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "message": {
                    "type": "string",
                    "description": "What you say, 1-4 short sentences. No product lists; the cards show them.",
                },
                "groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "e.g. 'Smart-casual dinner look'",
                            },
                            "kind": {"type": "string", "enum": ["outfit", "picks", "alternatives"]},
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "product_id": {"type": "integer"},
                                        "variant_id": {
                                            # null is allowed: open models send it instead of
                                            # omitting the key, and Groq enforces the schema.
                                            "type": ["integer", "null"],
                                            "description": "Omit (or null) until the size is known; the server fills it in.",
                                        },
                                        "role": {
                                            "type": "string",
                                            "enum": [
                                                "top",
                                                "bottom",
                                                "onepiece",
                                                "outerwear",
                                                "footwear",
                                                "accessory",
                                                "pick",
                                            ],
                                        },
                                        "reason": {
                                            "type": "string",
                                            "description": "One short, factual line on why it works.",
                                        },
                                    },
                                    "required": ["product_id", "role", "reason"],
                                },
                            },
                            "note": {"type": "string"},
                        },
                        "required": ["title", "kind", "items"],
                    },
                },
                "constraints": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "Everything you now know about what the shopper wants, carried to the next turn.",
                    "properties": {
                        "occasion": {"type": "string"},
                        "budget_max": {"type": "integer", "description": "Whole outfit, rupees."},
                        "apparel_size": {"type": "string"},
                        "footwear_size": {"type": "string"},
                        "gender": {"type": "string", "enum": ["men", "women"]},
                        "colours": {"type": "array", "items": {"type": "string"}},
                        "avoid_colours": {"type": "array", "items": {"type": "string"}},
                        "formality": {"type": "string", "enum": ["relaxed", "smart", "formal"]},
                        "notes": {"type": "string"},
                    },
                },
                "follow_ups": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Up to 4 short replies the shopper might tap next.",
                },
            },
            "required": ["message", "groups", "constraints", "follow_ups"],
        },
    },
]
# Inputs are validated with Pydantic before any tool runs (eager streaming skips server-side checks).
for _tool in TOOL_DEFINITIONS:
    _tool["eager_input_streaming"] = True


@dataclass
class ToolContext:
    session: AsyncSession
    store: Store | None
    stores: dict[str, Store]
    seen_product_ids: set[int] = field(default_factory=set)
    calls: list[dict[str, Any]] = field(default_factory=list)
    # Per-slot candidates the rule-based stylist considered; pipeline mode shows them to the model.
    shortlists: dict[str, list[int]] = field(default_factory=dict)
    # Compact style profile, present only when personalisation is on for account and chat.
    profile: dict[str, Any] | None = None
    # The shopper's uploaded garment: {"analysis": {...}, "vector": [...], "url": "..."}.
    upload: dict[str, Any] | None = None

    def store_for(self, code: str | None) -> Store | None:
        if code:
            store = self.stores.get(code.strip().upper())
            if store is None:
                raise ToolError(f"Unknown store code {code!r}. Valid: {', '.join(self.stores)}")
            return store
        return self.store


class ToolError(Exception):
    pass


def normalise_size(size: str | None) -> str | None:
    if not size:
        return None
    s = size.strip().upper()
    digits = "".join(ch for ch in s if ch.isdigit())
    return f"UK {int(digits)}" if digits else s


def to_product_filters(f: SearchFilters, store: Store | None) -> ProductFilters:
    genders = (
        [f.gender, "unisex"] if f.gender in ("men", "women") else ([f.gender] if f.gender else [])
    )
    size = normalise_size(f.size)
    return ProductFilters(
        category=f.categories,
        colour=[c.lower() for c in f.colours],
        gender=genders,
        size=[size] if size else [],
        min_price=f.min_price,
        max_price=f.max_price,
        store_id=store.id if store else None,
        in_stock=not f.include_out_of_stock,
    )


async def compact_products(
    session: AsyncSession, product_ids: list[int], store: Store | None
) -> list[dict[str, Any]]:
    """Facts the model needs to choose and explain, with sizes in stock at the store."""
    if not product_ids:
        return []
    products = {
        p.id: p
        for p in (
            await session.scalars(select(Product).where(Product.id.in_(product_ids)))
        ).unique()
    }
    stock_cond = and_(Inventory.variant_id == ProductVariant.id, Inventory.on_hand > 0)
    if store is not None:
        stock_cond = and_(stock_cond, Inventory.store_id == store.id)
    rows = await session.execute(
        select(ProductVariant.product_id, ProductVariant.id, ProductVariant.size, Inventory.on_hand)
        .join(Inventory, stock_cond)
        .where(ProductVariant.product_id.in_(product_ids), ProductVariant.is_active.is_(True))
        .order_by(ProductVariant.size_rank)
    )
    sizes: dict[int, dict[str, dict[str, Any]]] = {}
    for pid, vid, size, qty in rows.all():
        entry = sizes.setdefault(pid, {}).setdefault(
            size, {"size": size, "variant_id": vid, "qty": 0}
        )
        entry["qty"] += qty
    out = []
    for pid in product_ids:
        p = products.get(pid)
        if p is None:
            continue
        out.append(
            {
                "product_id": p.id,
                "name": p.name,
                "brand": p.brand.name,
                "category": p.category.slug,
                "slot": p.category.slot,
                "gender": p.gender,
                "colour": p.colour,
                "colour_family": p.colour_family,
                "pattern": p.pattern,
                "material": p.material,
                "fit": p.fit,
                "formality": p.formality,
                "style_tags": p.style_tags,
                "occasions": p.occasions,
                "price": p.price,
                **({"mrp": p.mrp} if p.mrp > p.price else {}),
                "in_stock_sizes": list(sizes.get(pid, {}).values()),
            }
        )
    return out


async def _search(ctx: ToolContext, args: SearchCatalogueInput) -> dict[str, Any]:
    store = ctx.store_for(args.filters.store_code)
    filters = to_product_filters(args.filters, store)
    query = " ".join(
        x for x in (args.query, args.filters.occasion, args.filters.style) if x
    ).strip()
    outcome = await hybrid_search(ctx.session, query or None, filters, parse=False)
    ids = [h.product_id for h in outcome.hits[: args.limit]]
    products = await compact_products(ctx.session, ids, store)
    ctx.seen_product_ids.update(ids)
    return {
        "store": store.code if store else "ALL",
        "total_matches": len(outcome.hits),
        "match": outcome.match,
        "products": products,
    }


async def _get_product(ctx: ToolContext, args: GetProductInput) -> dict[str, Any]:
    product = await ctx.session.scalar(
        select(Product).where(Product.id == args.product_id).options(selectinload(Product.variants))
    )
    if product is None:
        raise ToolError(f"No product with id {args.product_id}")
    (facts,) = await compact_products(ctx.session, [product.id], ctx.store) or [{}]
    rows = await ctx.session.execute(
        select(Inventory.variant_id, Store.code, Inventory.on_hand)
        .join(Store, Store.id == Inventory.store_id)
        .where(Inventory.variant_id.in_([v.id for v in product.variants]))
    )
    stock: dict[int, dict[str, int]] = {}
    for vid, code, qty in rows.all():
        stock.setdefault(vid, {})[code] = qty
    ctx.seen_product_ids.add(product.id)
    return {
        **facts,
        "is_active": product.is_active,
        "description": product.description,
        "variants": [
            {"variant_id": v.id, "size": v.size, "stock_by_store": stock.get(v.id, {})}
            for v in product.variants
            if v.is_active
        ],
    }


async def _similar(ctx: ToolContext, args: FindSimilarInput) -> dict[str, Any]:
    store = ctx.store_for(args.filters.store_code)
    hits = await find_similar(
        ctx.session, args.product_id, to_product_filters(args.filters, store), limit=args.limit
    )
    facts = {
        p["product_id"]: p
        for p in await compact_products(ctx.session, [h.product_id for h in hits], store)
    }
    ctx.seen_product_ids.update(facts)
    return {
        "store": store.code if store else "ALL",
        "products": [
            {**facts[h.product_id], "similarity": h.similarity, "why_similar": h.reasons}
            for h in hits
            if h.product_id in facts
        ],
    }


async def _inventory(ctx: ToolContext, args: CheckInventoryInput) -> dict[str, Any]:
    store = ctx.store_for(args.store_code)
    result = await variant_availability(ctx.session, args.variant_id, store.id if store else None)
    ctx.seen_product_ids.add(result.product_id)
    return {
        "variant_id": result.variant_id,
        "product_id": result.product_id,
        "size": result.size,
        "store": store.code if store else None,
        "on_hand_at_store": result.on_hand_at_store,
        "in_stock_at_store": result.in_stock_at_store,
        "other_stores": {
            s.store_code: s.on_hand for s in result.stores if not store or s.store_id != store.id
        },
    }


class BuildOutfitInput(BaseModel):
    model_config = {"extra": "forbid"}

    seed_product_id: int | None = None
    occasion: str | None = None
    budget_max: int | None = None
    gender: str | None = None
    apparel_size: str | None = None
    footwear_size: str | None = None
    formality: str | None = None
    colours: list[str] = []


async def _build_outfit_tool(ctx: ToolContext, args: BuildOutfitInput) -> dict[str, Any]:
    from app.agent.fallback import _build_outfit  # local import: fallback depends on this module
    from app.agent.schemas import SessionConstraints

    constraints = SessionConstraints.model_validate(
        {
            k: v
            for k, v in args.model_dump().items()
            if k != "seed_product_id" and v not in (None, [])
        }
    )
    focus = await ctx.session.get(Product, args.seed_product_id) if args.seed_product_id else None
    if args.seed_product_id and focus is None:
        raise ToolError(f"No product with id {args.seed_product_id}")
    group, status = await _build_outfit(ctx, constraints, focus)
    if group is None:
        hint = {
            "ask_gender": "Ask whether this is menswear or womenswear.",
            "over_budget": "Nothing fits the budget; suggest raising it.",
        }.get(status.split(":")[0], status)
        return {"outfit": None, "status": status, "hint": hint}
    ids = [i.product_id for i in group.items]
    facts = {p["product_id"]: p for p in await compact_products(ctx.session, ids, ctx.store)}
    alternatives = {
        slot: await compact_products(
            ctx.session, [pid for pid in pids if pid not in ids][:3], ctx.store
        )
        for slot, pids in ctx.shortlists.items()
    }
    return {
        "outfit": [
            {"role": i.role, "suggested_reason": i.reason, **facts.get(i.product_id, {})}
            for i in group.items
        ],
        "total": sum(facts[i]["price"] for i in ids if i in facts),
        "alternatives": alternatives,
    }


HANDLERS: dict[str, tuple[type[BaseModel], Any]] = {
    "build_outfit": (BuildOutfitInput, _build_outfit_tool),
    "search_catalogue": (SearchCatalogueInput, _search),
    "get_product": (GetProductInput, _get_product),
    "find_similar_products": (FindSimilarInput, _similar),
    "check_variant_inventory": (CheckInventoryInput, _inventory),
}


async def execute_tool(ctx: ToolContext, name: str, raw_input: Any) -> tuple[str, bool]:
    """Run one tool call. Returns (JSON content, is_error); never raises for model mistakes."""
    start = time.perf_counter()
    record: dict[str, Any] = {"name": name, "input": raw_input}
    try:
        if name not in HANDLERS:
            raise ToolError(f"Unknown tool {name!r}")
        model, handler = HANDLERS[name]
        if not isinstance(raw_input, dict):
            raise ToolError("Tool input must be a JSON object")
        result = await handler(ctx, model.model_validate(raw_input))
        record.update(
            ok=True, results=len(result.get("products", [])) if isinstance(result, dict) else None
        )
        return json.dumps(result, ensure_ascii=False, separators=(",", ":")), False
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        record.update(ok=False, error=problems)
        return json.dumps({"error": f"Invalid input: {problems}"}), True
    except (ToolError, AppError) as exc:
        message = getattr(exc, "message", str(exc))
        record.update(ok=False, error=message)
        return json.dumps({"error": message}), True
    finally:
        record["ms"] = round((time.perf_counter() - start) * 1000, 1)
        ctx.calls.append(record)
