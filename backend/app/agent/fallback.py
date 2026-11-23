"""Deterministic Gabriella for when no LLM key is configured.

Same contract as the Claude agent (a validated `Recommendation`), built from the query parser,
hybrid search with hard stock/size/budget filters, and the rules in `styling.py`. Less
conversational, but every product it shows is real, in stock and explainable.
"""

import itertools
import re
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import Emit, TurnResult
from app.agent.schemas import (
    Recommendation,
    RecommendationGroup,
    RecommendedItem,
    SessionConstraints,
)
from app.agent.styling import colour_score, formality_word, pairing_reason, target_formality
from app.agent.tools import ToolContext
from app.agent.validator import repair, validate
from app.db.models import Category, Product, ProductVariant
from app.retrieval.query_parser import parse_query
from app.retrieval.search import hybrid_search
from app.retrieval.similar import find_similar
from app.schemas.catalogue import ProductFilters
from app.services.inventory import variant_availability

_SIMILAR = re.compile(
    r"\b(similar|like (?:this|these|that|those|it)|alternatives?|instead|something else|other options?)\b",
    re.I,
)
_AVAILABILITY = re.compile(
    r"\b(available|availability|in stock|do you have|have (?:it|this|these|them)|stock)\b", re.I
)
_OUTFIT = re.compile(
    r"\b(outfits?|looks?|wear|go(?:es)? with|pair|match|styl(?:e|ing)|complete|what should i|dress me)\b",
    re.I,
)
_RESET = re.compile(r"\b(start (?:fresh|over|again)|reset|forget (?:that|everything))\b", re.I)
_LESS_FORMAL = re.compile(
    r"\b(less formal|more casual|dress(?:ed)? down|relaxed|chill(?:er)?)\b", re.I
)
_MORE_FORMAL = re.compile(r"\b(more formal|dressier|smarter|dress(?:ed)? up|sharper)\b", re.I)

FORMALITY_STEPS = ["relaxed", "smart", "formal"]
ETHNIC_OCCASIONS = {"wedding", "festive"}
ETHNIC_CATEGORIES = {"kurtas", "nehru-jackets", "ethnic-bottoms", "juttis"}
CANDIDATES_PER_SLOT = 8


def update_constraints(current: SessionConstraints, text: str) -> SessionConstraints:
    if _RESET.search(text):
        return SessionConstraints()
    parsed = parse_query(text)
    c = current.model_copy(deep=True)
    if parsed.max_price:
        c.budget_max = parsed.max_price
    for size in parsed.sizes:
        if size.startswith("UK"):
            c.footwear_size = size
        else:
            c.apparel_size = size
    gender = next((g for g in parsed.genders if g in ("men", "women")), None)
    if gender:
        c.gender = gender  # type: ignore[assignment]
    if parsed.occasions and parsed.occasions[0] != c.occasion:
        c.occasion = parsed.occasions[0]
        c.formality = None  # a new occasion sets its own dress code unless restated below
    style_formality = {"casual": "relaxed", "smart-casual": "smart", "formal": "formal"}
    relative = _LESS_FORMAL.search(text) or _MORE_FORMAL.search(text)
    for style in [] if relative else parsed.styles:  # "more formal" is a step, not "formal"
        if style in style_formality:
            c.formality = style_formality[style]  # type: ignore[assignment]
            break
    if parsed.colours:
        c.colours = parsed.colours[:3]
    step = c.formality or ("formal" if target_formality(c.occasion, None) >= 4 else "smart")
    if _LESS_FORMAL.search(text):
        c.formality = FORMALITY_STEPS[max(0, FORMALITY_STEPS.index(step) - 1)]  # type: ignore[assignment]
    elif _MORE_FORMAL.search(text):
        c.formality = FORMALITY_STEPS[min(2, FORMALITY_STEPS.index(step) + 1)]  # type: ignore[assignment]
    return c


DRESSED_UP_OCCASIONS = {"dinner", "date", "office", "wedding", "festive", "party"}
TOO_CASUAL_FOR_DRESSED_UP = {"shorts", "joggers", "hoodies-sweatshirts", "caps", "sandals"}


async def _slot_categories(
    session: AsyncSession, slot: str, ethnic: bool, occasion: str | None = None
) -> list[str]:
    slugs = (await session.scalars(select(Category.slug).where(Category.slot == slot))).all()
    if occasion in DRESSED_UP_OCCASIONS:
        slugs = [s for s in slugs if s not in TOO_CASUAL_FOR_DRESSED_UP]
    if slot in ("top", "bottom", "footwear") and ethnic:
        preferred = [s for s in slugs if s in ETHNIC_CATEGORIES]
        if slot == "footwear":
            preferred += ["loafers", "formal-shoes"]
        return preferred or list(slugs)
    return [s for s in slugs if s not in ETHNIC_CATEGORIES]


async def _candidates(
    ctx: ToolContext,
    slot: str,
    c: SessionConstraints,
    gender: str,
    max_price: int | None,
    target: int,
) -> list[tuple[Product, float]]:
    """Shortlist for one slot: in stock in the shopper's size, scored on formality,
    occasion and retrieval rank. Colour harmony is scored later, across the whole outfit."""
    session = ctx.session
    ethnic = c.occasion in ETHNIC_OCCASIONS
    size = (
        c.footwear_size
        if slot == "footwear"
        else (c.apparel_size if slot in ("top", "bottom", "onepiece") else None)
    )
    query = " ".join(x for x in (c.occasion, formality_word(target), *c.colours) if x)
    filters = ProductFilters(
        category=await _slot_categories(session, slot, ethnic, c.occasion),
        gender=[gender, "unisex"],
        size=[size] if size else [],
        max_price=max_price,
        store_id=ctx.store.id if ctx.store else None,
        in_stock=True,
    )
    outcome = await hybrid_search(session, query or None, filters, parse=False)
    ids = [h.product_id for h in outcome.hits[:24]]
    if len(ids) < CANDIDATES_PER_SLOT:
        # Keyword-only mode (no embeddings yet) can miss good pieces; top up from the
        # stock-filtered listing so a slot is never empty just because of wording.
        listing = await hybrid_search(session, None, filters, parse=False)
        ids += [h.product_id for h in listing.hits[:24] if h.product_id not in ids]
    products = (
        {
            p.id: p
            for p in (await session.scalars(select(Product).where(Product.id.in_(ids)))).unique()
        }
        if ids
        else {}
    )
    avoid = {a.lower() for a in c.avoid_colours}
    scored = []
    for rank, pid in enumerate(ids):
        p = products.get(pid)
        if p is None or p.colour.lower() in avoid or p.colour_family in avoid:
            continue
        # Accessories must suit the occasion (no baseball caps at weddings); other pieces
        # may be at most two steps away and are penalised per step.
        if abs(p.formality - target) > (1 if slot == "accessory" else 2):
            continue
        base = (
            -0.3 * abs(p.formality - target)
            + 0.35 / (1 + rank)
            + (0.15 if c.occasion and c.occasion in p.occasions else 0)
        )
        scored.append((p, base))
    scored.sort(key=lambda t: -t[1])
    shortlist = scored[: CANDIDATES_PER_SLOT - 3]
    # Keep a few of the cheapest decent options so tight budgets still have a combination.
    for entry in sorted(scored, key=lambda t: t[0].price):
        if len(shortlist) >= CANDIDATES_PER_SLOT:
            break
        if entry not in shortlist:
            shortlist.append(entry)
    return shortlist


def _harmony(products: list[Product]) -> float:
    families = [p.colour_family for p in products]
    return sum(
        colour_score(f, families[:i] + families[i + 1 :]) for i, f in enumerate(families)
    ) / max(1, len(families))


def _reason(p: Product, anchor: Product | None, target: int) -> str:
    parts = []
    if anchor is not None and anchor.id != p.id:
        pairing = pairing_reason(p.colour, p.colour_family, anchor.colour, anchor.colour_family)
        if pairing:
            parts.append(pairing[0].upper() + pairing[1:])
    if abs(p.formality - target) <= 1:
        parts.append(
            f"{formality_word(p.formality).capitalize()} {p.material.lower()} to match the occasion"
        )
    return ". ".join(parts[:2]) or f"{p.colour} {p.material.lower()}, {p.fit.lower()} fit"


async def _build_outfit(
    ctx: ToolContext, c: SessionConstraints, focus: Product | None
) -> tuple[RecommendationGroup | None, str]:
    gender = c.gender or (focus.gender if focus and focus.gender != "unisex" else None)
    if gender is None:
        return None, "ask_gender"
    anchor_slot = focus.category.slot if focus else None
    required = (
        ["onepiece", "footwear"] if anchor_slot == "onepiece" else ["top", "bottom", "footwear"]
    )
    required = [s for s in required if s != anchor_slot]
    remaining = (c.budget_max - (focus.price if focus else 0)) if c.budget_max else None
    if remaining is not None and remaining <= 0:
        return None, "over_budget"
    target = target_formality(c.occasion, c.formality)

    pools = {slot: await _candidates(ctx, slot, c, gender, remaining, target) for slot in required}
    if any(not pool for pool in pools.values()):
        return None, "missing_slot"
    accessories: list[tuple[Product, float] | None] = [None]
    if anchor_slot != "accessory":
        accessories += await _candidates(ctx, "accessory", c, gender, remaining, target)

    # Score every combination of the shortlists under the whole budget (at most ~5k combos).
    best: tuple[float, list[Product]] | None = None
    fixed = [focus] if focus else []
    for combo in itertools.product(*(pools[s] for s in required), accessories):
        picked = [entry for entry in combo if entry is not None]
        items = fixed + [p for p, _ in picked]
        if remaining is not None and sum(p.price for p, _ in picked) > remaining:
            continue
        score = sum(base for _, base in picked) + 1.2 * _harmony(items) + (0.1 if combo[-1] else 0)
        if best is None or score > best[0]:
            best = (score, items)
    if best is None:
        cheapest = sum(min(p.price for p, _ in pools[s]) for s in required) + (
            focus.price if focus else 0
        )
        return None, f"over_budget:{cheapest}"

    chosen = best[1]
    ctx.seen_product_ids.update(p.id for p in chosen)
    anchor = focus or chosen[0]
    items = [
        RecommendedItem(
            product_id=p.id,
            role=p.category.slot
            if p.category.slot
            in ("top", "bottom", "onepiece", "outerwear", "footwear", "accessory")
            else "pick",  # type: ignore[arg-type]
            reason="The piece you're styling"
            if focus and p.id == focus.id
            else _reason(
                p, anchor if anchor.id != p.id else (chosen[1] if len(chosen) > 1 else None), target
            ),
        )
        for p in chosen
    ]
    occasion = (c.occasion or formality_word(target)).replace("-", " ")
    title = f"Built around your {focus.name.lower()}" if focus else f"{occasion.capitalize()} look"
    return RecommendationGroup(title=title, kind="outfit", items=items), "ok"


async def _picks(ctx: ToolContext, text: str, c: SessionConstraints) -> tuple[list[int], bool]:
    parsed = parse_query(text)
    base = ProductFilters(
        category=parsed.categories,
        colour=parsed.colours,
        gender=[c.gender, "unisex"] if c.gender else [],
        size=parsed.sizes,
        max_price=c.budget_max,
        on_sale=parsed.on_sale,
        store_id=ctx.store.id if ctx.store else None,
        in_stock=True,
    )
    outcome = await hybrid_search(ctx.session, parsed.text or text, base, parse=False)
    ids = [h.product_id for h in outcome.hits[:6]]
    if ids or ctx.store is None:
        return ids, True
    # Nothing here: look across every store so we can say where it is instead.
    outcome = await hybrid_search(
        ctx.session, parsed.text or text, base.model_copy(update={"store_id": None}), parse=False
    )
    return [h.product_id for h in outcome.hits[:6]], False


async def run_fallback_turn(
    ctx: ToolContext, constraints: dict[str, Any], focus_id: int | None, text: str, emit: Emit
) -> TurnResult:
    session = ctx.session
    try:
        current = SessionConstraints.model_validate(constraints or {})
    except ValidationError:
        current = SessionConstraints()
    c = update_constraints(current, text)
    focus = await session.get(Product, focus_id) if focus_id else None
    if focus is not None:
        ctx.seen_product_ids.add(focus.id)
    where = f" at {ctx.store.city}" if ctx.store else ""
    groups: list[RecommendationGroup] = []
    follow_ups: list[str] = []

    if _RESET.search(text):
        message = "Fresh start. What are you shopping for today?"
        follow_ups = [
            "A casual dinner outfit",
            "Office wear under ₹5,000",
            "Something for a wedding",
        ]
    elif focus is not None and _AVAILABILITY.search(text) and not _OUTFIT.search(text):
        await emit({"type": "status", "text": f"Checking stock{where}…"})
        message, groups = await _availability(ctx, focus, c)
        follow_ups = ["Show similar pieces", "Style this into an outfit"]
    elif focus is not None and _SIMILAR.search(text):
        await emit({"type": "status", "text": f"Finding similar pieces{where}…"})
        size = c.footwear_size if focus.category.slot == "footwear" else c.apparel_size
        hits = await find_similar(
            session,
            focus.id,
            ProductFilters(
                size=[size] if size else [],
                max_price=c.budget_max,
                store_id=ctx.store.id if ctx.store else None,
                in_stock=True,
            ),
            limit=6,
        )
        ctx.seen_product_ids.update(h.product_id for h in hits)
        groups = (
            [
                RecommendationGroup(
                    title=f"Like your {focus.name.lower()}",
                    kind="alternatives",
                    items=[
                        RecommendedItem(
                            product_id=h.product_id,
                            role="pick",
                            reason=", ".join(h.reasons[:2]) or "A close match",
                        )
                        for h in hits
                    ],
                )
            ]
            if hits
            else []
        )
        message = (
            f"Here are pieces close to the {focus.name.lower()} that are in stock{where}."
            if hits
            else f"I couldn't find a close match in stock{where}. Try another size or store."
        )
        follow_ups = ["Style the first one into an outfit", "Show cheaper options"]
    elif _OUTFIT.search(text) or c.occasion or focus is not None:
        await emit({"type": "status", "text": f"Putting together a look{where}…"})
        group, status = await _build_outfit(ctx, c, focus)
        if status == "ask_gender":
            message = "Happy to put a look together. Are you shopping for menswear or womenswear?"
            follow_ups = ["Menswear", "Womenswear"]
        elif status.startswith("over_budget"):
            cheapest = int(status.split(":")[1]) if ":" in status else None
            message = f"I couldn't fit a full {(c.occasion or 'outfit').replace('-', ' ')} look in stock{where} within ₹{c.budget_max:,}."
            if cheapest:
                rounded = -(-cheapest // 500) * 500
                message += f" The most affordable complete look here comes to about ₹{cheapest:,}."
                follow_ups = [f"Show it under ₹{rounded:,}", "Show separates instead"]
            else:
                follow_ups = ["Raise the budget", "Show separates instead"]
        elif group is None or len(group.items) < 2:
            message = f"I couldn't build a full outfit in stock{where} with those constraints. Try a higher budget or another store."
            follow_ups = ["Raise the budget", "Show what's available online"]
        else:
            groups = [group]
            budget = f" under ₹{c.budget_max:,}" if c.budget_max else ""
            occasion = (c.occasion or "versatile").replace("-", " ")
            article = "an" if occasion[0] in "aeiou" else "a"
            message = f"Here's {article} {occasion} look{budget}, all in stock{where}" + (
                " in your sizes."
                if c.apparel_size or c.footwear_size
                else ". Tell me your sizes and I'll check them."
            )
            follow_ups = ["Make it less formal", "Make it more formal", "Swap the shoes"]
    else:
        await emit({"type": "status", "text": f"Searching the catalogue{where}…"})
        ids, here = await _picks(ctx, text, c)
        ctx.seen_product_ids.update(ids)
        groups = (
            [
                RecommendationGroup(
                    title="Top picks",
                    kind="picks",
                    items=[RecommendedItem(product_id=i, role="pick", reason="") for i in ids],
                )
            ]
            if ids
            else []
        )
        message = "Here's what I found" + (
            f" in stock{where}."
            if here
            else f". None are in stock{where}, but other stores have them."
        )
        if not ids:
            message = "I couldn't find anything matching that. Could you describe it differently?"
        follow_ups = [
            "Build an outfit around the first one",
            "Under ₹3,000",
            "Show me similar styles",
        ]

    raw = Recommendation(
        message=message, groups=groups, constraints=c, follow_ups=follow_ups
    ).model_dump()
    await emit({"type": "status", "text": "Checking every piece against live stock…"})
    report = await validate(session, raw, store=ctx.store, seen_product_ids=ctx.seen_product_ids)
    validation: dict[str, Any] = {
        "attempts": 1,
        "problems": report.problems,
        "checked_items": report.checked_items,
    }
    rec = report.recommendation
    assert rec is not None
    if not report.ok:
        rec, notes = await repair(session, report, store=ctx.store)
        validation["repairs"] = notes
    ctx.calls.append(
        {"name": "fallback", "intent": groups[0].kind if groups else "message", "ok": report.ok}
    )
    return TurnResult(rec, validation, model="deterministic")


async def _availability(
    ctx: ToolContext, focus: Product, c: SessionConstraints
) -> tuple[str, list[RecommendationGroup]]:
    session = ctx.session
    size = c.footwear_size if focus.category.slot == "footwear" else c.apparel_size
    variants = (
        await session.scalars(select(ProductVariant).where(ProductVariant.product_id == focus.id))
    ).all()
    where = ctx.store.city if ctx.store else "any store"
    if size is None:
        sizes = []
        for v in variants:
            a = await variant_availability(session, v.id, ctx.store.id if ctx.store else None)
            if (a.on_hand_at_store or 0) > 0 or (
                ctx.store is None and any(s.on_hand for s in a.stores)
            ):
                sizes.append(v.size)
        return (
            f"The {focus.name.lower()} is in stock in {', '.join(sizes)} at {where}. Which size do you wear?"
            if sizes
            else f"The {focus.name.lower()} is sold out at {where} right now."
        ), []
    variant = next((v for v in variants if v.size == size), None)
    if variant is None:
        return f"The {focus.name.lower()} doesn't come in {size}.", []
    a = await variant_availability(session, variant.id, ctx.store.id if ctx.store else None)
    if a.in_stock_at_store or (ctx.store is None and any(s.on_hand for s in a.stores)):
        left = (
            f" ({a.on_hand_at_store} left)"
            if a.on_hand_at_store and a.on_hand_at_store <= 3
            else ""
        )
        group = RecommendationGroup(
            title="In stock",
            kind="picks",
            items=[
                RecommendedItem(
                    product_id=focus.id,
                    variant_id=variant.id,
                    role="pick",
                    reason=f"Size {size}, ready to try on",
                )
            ],
        )
        return f"Yes, the {focus.name.lower()} in {size} is in stock at {where}{left}.", [group]
    elsewhere = [s.city for s in a.stores if s.on_hand > 0]
    hits = await find_similar(
        session,
        focus.id,
        ProductFilters(size=[size], store_id=ctx.store.id if ctx.store else None, in_stock=True),
        limit=4,
    )
    ctx.seen_product_ids.update(h.product_id for h in hits)
    groups = (
        [
            RecommendationGroup(
                title=f"Similar, in {size} at {where}",
                kind="alternatives",
                items=[
                    RecommendedItem(
                        product_id=h.product_id, role="pick", reason=", ".join(h.reasons[:2])
                    )
                    for h in hits
                ],
            )
        ]
        if hits
        else []
    )
    message = f"The {focus.name.lower()} in {size} is sold out at {where}"
    message += (
        f", but {', '.join(elsewhere[:3])} {'has' if len(elsewhere) == 1 else 'have'} it."
        if elsewhere
        else "."
    )
    if hits:
        message += " These are close alternatives you can buy here today."
    return message, groups
