"""Server-side grounding checks for every recommendation before the shopper sees it.

`validate` reports problems the model can fix (wrong size, sold out, over budget, a product it
never retrieved). `repair` is the last resort after retries: it swaps invalid items for in-stock
alternatives in the same slot, or drops them, so nothing invalid is ever displayed.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schemas import Recommendation, RecommendedItem
from app.db.models import Category, Inventory, Product, ProductVariant, Store
from app.retrieval.similar import find_similar
from app.schemas.catalogue import ProductFilters

APPAREL_SLOTS = {"top", "bottom", "onepiece", "outerwear"}

# Garment nouns a reason may open with, and the other words each category answers to. A reason
# whose first garment noun doesn't fit its own product ("White sneakers keep it relaxed" under a
# loafer) was written for a different item, usually one the model swapped out.
CATEGORY_SYNONYMS: dict[str, set[str]] = {
    "t-shirts": {"tee", "t-shirt"},
    "knitwear": {"sweater", "jumper", "cardigan", "knit", "pullover"},
    "hoodies-sweatshirts": {"hoodie", "sweatshirt"},
    "jeans": {"jean", "denim"},
    "trousers": {"trouser", "pant", "slack"},
    "chinos": {"chino", "pant", "trouser"},
    "joggers": {"jogger", "pant"},
    "day-evening-dresses": {"dress", "gown"},
    "formal-shoes": {"shoe", "oxford", "derby", "brogue"},
    "loafers": {"loafer", "shoe", "moccasin"},
    "sneakers": {"sneaker", "trainer", "shoe"},
    "boots": {"boot", "shoe"},
    "heels-flats": {"heel", "pump", "shoe"},
    "sandals": {"sandal"},
    "juttis-mojaris": {"jutti", "mojari", "shoe"},
    "bags": {"bag", "tote", "handbag"},
    "scarves-stoles": {"scarf", "stole"},
    "churidars-palazzos": {"churidar", "palazzo", "pant"},
}
GARMENT_NOUNS = sorted(
    {w for ws in CATEGORY_SYNONYMS.values() for w in ws}
    | {"shirt", "polo", "blouse", "blazer", "jacket", "kurta", "skirt", "short", "belt", "cap"},
    key=len,
    reverse=True,  # longest first, so "t-shirt" wins over "shirt"
)
_NOUN = re.compile(r"\b(" + "|".join(map(re.escape, GARMENT_NOUNS)) + r")(?:e?s)?\b", re.I)


def reason_fits(reason: str, product: Product) -> bool:
    """True unless the reason opens by describing a different kind of garment."""
    first = _NOUN.search(reason or "")
    if first is None:
        return True
    noun = first.group(1).lower()
    word = r"[a-z]+(?:-[a-z]+)*"
    name = re.findall(word, product.name.lower())
    # Name parts count too ("Cap-Toe Derbys" may be called a cap-toe), but not category parts:
    # "T-Shirts" must not make every tee answer to "shirt".
    parts = (
        name
        + [p for w in name if "-" in w for p in w.split("-")]
        + re.findall(word, product.category.name.lower())
    )
    own = {w for word in parts for w in (word, word.removesuffix("s"), word.removesuffix("es"))}
    return noun in own or noun in CATEGORY_SYNONYMS.get(product.category.slug, set())


def factual_reason(product: Product) -> str:
    return f"{product.colour} {product.material.lower()}, {product.fit.lower()} fit"


@dataclass
class ItemFacts:
    product: Product
    slot: str | None
    variants: dict[int, tuple[str, int]]  # variant_id -> (size, on_hand at store / anywhere)


@dataclass
class ValidationReport:
    recommendation: Recommendation | None
    problems: list[str] = field(default_factory=list)
    invalid: set[tuple[int, int]] = field(default_factory=set)  # (group index, item index)
    checked_items: int = 0
    reasons_rewritten: int = 0

    @property
    def ok(self) -> bool:
        return self.recommendation is not None and not self.problems


async def _facts(
    session: AsyncSession, product_ids: set[int], store: Store | None
) -> dict[int, ItemFacts]:
    if not product_ids:
        return {}
    products = (
        (
            await session.execute(
                select(Product, Category.slot)
                .join(Category, Category.id == Product.category_id)
                .where(Product.id.in_(product_ids))
            )
        )
        .unique()
        .all()
    )
    join = and_(Inventory.variant_id == ProductVariant.id)
    if store is not None:
        join = and_(join, Inventory.store_id == store.id)
    rows = await session.execute(
        select(
            ProductVariant.product_id,
            ProductVariant.id,
            ProductVariant.size,
            func.coalesce(func.sum(Inventory.on_hand), 0),
        )
        .outerjoin(Inventory, join)
        .where(ProductVariant.product_id.in_(product_ids), ProductVariant.is_active.is_(True))
        .group_by(ProductVariant.id)
    )
    variants: dict[int, dict[int, tuple[str, int]]] = {}
    for pid, vid, size, qty in rows.all():
        variants.setdefault(pid, {})[vid] = (size, int(qty))
    return {p.id: ItemFacts(p, slot, variants.get(p.id, {})) for p, slot in products}


def _size_for(item_slot: str | None, rec: Recommendation) -> str | None:
    c = rec.constraints
    if item_slot == "footwear":
        return c.footwear_size
    if item_slot in APPAREL_SLOTS:
        return c.apparel_size
    return None


def _label(facts: ItemFacts | None, item: RecommendedItem) -> str:
    return f"product {item.product_id}" + (
        f" ({facts.product.name}, {facts.product.colour})" if facts else ""
    )


async def validate(
    session: AsyncSession,
    raw: Any,
    *,
    store: Store | None,
    seen_product_ids: set[int],
) -> ValidationReport:
    try:
        rec = Recommendation.model_validate(raw)
    except ValidationError as exc:
        problems = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        return ValidationReport(None, problems=problems)

    report = ValidationReport(rec)
    ids = {item.product_id for g in rec.groups for item in g.items}
    facts = await _facts(session, ids, store)
    where = f"at {store.name}" if store else "in any store"

    for gi, group in enumerate(rec.groups):
        seen_in_group: set[int] = set()
        for ii, item in enumerate(group.items):
            report.checked_items += 1
            f = facts.get(item.product_id)
            label = _label(f, item)

            def fail(msg: str, gi: int = gi, ii: int = ii) -> None:
                report.problems.append(f"groups[{gi}].items[{ii}] {msg}")
                report.invalid.add((gi, ii))

            if f is None:
                fail(f"{label} does not exist. Only use IDs returned by your tools.")
                continue
            if item.product_id not in seen_product_ids:
                fail(
                    f"{label} was not returned by any tool this conversation. Search for it first."
                )
                continue
            if not f.product.is_active:
                fail(f"{label} is discontinued.")
                continue
            if item.product_id in seen_in_group:
                fail(f"{label} appears twice in the same group.")
                continue
            seen_in_group.add(item.product_id)

            wanted_size = _size_for(f.slot, rec)
            if item.variant_id is not None:
                if item.variant_id not in f.variants:
                    fail(f"variant {item.variant_id} does not belong to {label}.")
                    continue
                size, qty = f.variants[item.variant_id]
                if wanted_size and size != wanted_size:
                    fail(
                        f"variant {item.variant_id} is size {size}, but the shopper wears {wanted_size}."
                    )
                    continue
                if qty <= 0:
                    fail(f"{label} in size {size} is out of stock {where}.")
                    continue
            else:
                in_stock = {size: vid for vid, (size, qty) in f.variants.items() if qty > 0}
                if wanted_size:
                    if wanted_size not in in_stock:
                        fail(f"{label} is not in stock in size {wanted_size} {where}.")
                        continue
                    item.variant_id = in_stock[wanted_size]  # size known: pin the exact variant
                elif not in_stock:
                    fail(f"{label} has no sizes in stock {where}.")
                    continue

        budget = rec.constraints.budget_max
        if budget:
            prices = [
                facts[i.product_id].product.price for i in group.items if i.product_id in facts
            ]
            if group.kind == "outfit" and sum(prices) > budget:
                report.problems.append(
                    f"groups[{gi}] '{group.title}' totals ₹{sum(prices):,}, over the ₹{budget:,} budget."
                )
            elif group.kind != "outfit":
                for ii, item in enumerate(group.items):
                    if item.product_id in facts and facts[item.product_id].product.price > budget:
                        report.problems.append(
                            f"groups[{gi}].items[{ii}] costs more than the ₹{budget:,} budget."
                        )
                        report.invalid.add((gi, ii))

    # Reasons are shown under each card, so they must describe that card.
    for group in rec.groups:
        for item in group.items:
            f = facts.get(item.product_id)
            if f is not None and item.reason and not reason_fits(item.reason, f.product):
                item.reason = factual_reason(f.product)
                report.reasons_rewritten += 1
    return report


def owned_product_ids(profile: dict | None) -> set[int]:
    """Products the shopper bought recently or returned: never suggest these again."""
    profile = profile or {}
    return set(profile.get("recent_product_ids", [])) | set(profile.get("returned_product_ids", []))


async def repair(
    session: AsyncSession,
    report: ValidationReport,
    *,
    store: Store | None,
    avoid: set[int] | None = None,
) -> tuple[Recommendation, list[str]]:
    """Make a recommendation displayable: swap or drop invalid items, then enforce budgets.
    Replacements never come from `avoid` (e.g. what the shopper already owns)."""
    rec = report.recommendation
    assert rec is not None
    notes: list[str] = []
    budget = rec.constraints.budget_max

    for gi, group in enumerate(rec.groups):
        kept: list[RecommendedItem] = []
        used = {i.product_id for i in group.items} | (avoid or set())
        for ii, item in enumerate(group.items):
            if (gi, ii) not in report.invalid:
                kept.append(item)
                continue
            product = await session.get(Product, item.product_id)
            replacement = None
            if product is not None:
                size = _size_for(product.category.slot, rec)
                hits = await find_similar(
                    session,
                    product.id,
                    ProductFilters(
                        size=[size] if size else [],
                        in_stock=True,
                        store_id=store.id if store else None,
                        max_price=budget if budget and group.kind != "outfit" else None,
                    ),
                    limit=5,
                )
                replacement = next((h for h in hits if h.product_id not in used), None)
            if replacement:
                facts = (await _facts(session, {replacement.product_id}, store))[
                    replacement.product_id
                ]
                variant = next(
                    (
                        vid
                        for vid, (sz, q) in facts.variants.items()
                        if q > 0 and (not size or sz == size)
                    ),
                    None,
                )
                used.add(replacement.product_id)
                kept.append(
                    item.model_copy(
                        update={
                            "product_id": replacement.product_id,
                            "variant_id": variant,
                            "reason": f"Swapped in for {product.name}, which isn't available in your size here. "
                            + (replacement.reasons[0] if replacement.reasons else ""),
                        }
                    )
                )
                notes.append(f"replaced {item.product_id} with {replacement.product_id}")
            else:
                notes.append(f"dropped {item.product_id}")
        group.items = kept

    # Enforce outfit budgets by dropping the least essential pieces first.
    if budget:
        order = ["accessory", "outerwear", "pick", "footwear", "top", "bottom", "onepiece"]
        for group in rec.groups:
            if group.kind != "outfit":
                continue
            prices = {
                p.id: p.price
                for p in (
                    await session.scalars(
                        select(Product).where(Product.id.in_([i.product_id for i in group.items]))
                    )
                ).unique()
            }
            while group.items and sum(prices.get(i.product_id, 0) for i in group.items) > budget:
                victim = min(
                    group.items, key=lambda i: (order.index(i.role), -prices.get(i.product_id, 0))
                )
                group.items.remove(victim)
                notes.append(f"dropped {victim.product_id} for budget")

    rec.groups = [g for g in rec.groups if g.items]
    return rec, notes
