"""Deterministic generator for the simulated catalogue.

Pure Python: produces plain dataclasses so it can be unit-tested without a database.
The same seed always yields the same catalogue, images and stock levels.
"""

import random
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from seed.taxonomy import (
    ACCENT_COLOURS,
    APPAREL_SIZES,
    BRANDS,
    COLOURS,
    FOOTWEAR_SIZES,
    SIZE_RANK,
    SPECS,
    STORES,
    TIER_MULTIPLIER,
    Spec,
)

DEFAULT_SEED = 20261107
CATALOGUE_EPOCH = datetime(2026, 11, 1, tzinfo=UTC)

PATTERN_WORD = {
    "striped": "Striped",
    "checked": "Checked",
    "printed": "Printed",
    "textured": "Textured",
}
SIZE_WEIGHT = {"XS": 0.5, "S": 0.85, "M": 1.0, "L": 1.0, "XL": 0.7, "XXL": 0.4}


@dataclass
class GenVariant:
    sku: str
    size: str
    size_rank: int
    stock: dict[str, int]  # store code -> on hand


@dataclass
class GenProduct:
    key: int  # 1-based position, stable for a given seed
    style_code: str
    slug: str
    name: str
    brand_slug: str
    category_slug: str
    shape: str
    gender: str
    colour: str
    colour_hex: str
    colour_family: str
    secondary_colours: list[str]
    pattern: str
    material: str
    fit: str
    style_tags: list[str]
    occasions: list[str]
    seasons: list[str]
    formality: int
    price: int
    mrp: int
    description: str
    popularity: int
    is_active: bool
    created_at: datetime
    variants: list[GenVariant] = field(default_factory=list)


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _retail_price(raw: float) -> int:
    """Round to a believable shelf price: 1,299 / 1,499 / 2,999 …"""
    step = 100 if raw < 5000 else 500
    return max(299, int(round(raw / step)) * step - 1)


def _weighted(rng: random.Random, options: tuple[tuple[str, float], ...]) -> str:
    names, weights = zip(*options, strict=True)
    return rng.choices(names, weights=weights, k=1)[0]


def _sizes_for(spec: Spec, gender: str) -> list[str]:
    if spec.sizing == "apparel":
        return APPAREL_SIZES[gender]
    if spec.sizing == "footwear":
        return FOOTWEAR_SIZES[gender]
    if spec.sizing == "belt":
        return ["S", "M", "L", "XL"]
    return ["One Size"]


def _name(rng: random.Random, spec: Spec, fit: str, material: str, pattern: str) -> str:
    templates = [t for t in spec.names if pattern != "solid" or "{pattern}" not in t]
    template = rng.choice(templates)
    fit_word = "Classic" if fit == "Regular" else fit
    name = template.format(fit=fit_word, material=material, pattern=PATTERN_WORD.get(pattern, ""))
    return re.sub(r"\s+", " ", name).strip()


_CHARACTER = {
    "minimal": "Clean lines and no fuss — it quietly works with almost everything.",
    "smart-casual": "Sharp enough for the office, relaxed enough for dinner after.",
    "classic": "A wardrobe staple with details that won't date.",
    "casual": "Made for easy days and unplanned plans.",
    "streetwear": "A slightly bigger, bolder take for off-duty layering.",
    "athleisure": "Soft, stretchy and built to move between errands and the gym.",
    "travel": "Packs small, creases less and looks put-together on arrival.",
    "formal": "Precise tailoring for meetings, ceremonies and everything in between.",
    "party": "Catches the light and holds its own after dark.",
    "festive": "Rich colour and texture for celebrations and family functions.",
    "ethnic": "Traditional craft with a contemporary, lighter silhouette.",
    "bohemian": "Free-flowing and relaxed with a hint of the handmade.",
}
_MATERIAL_NOTE = {
    "linen": "Breathable linen that softens with every wash.",
    "denim": "Sturdy denim that fades in naturally over time.",
    "wool": "Naturally temperature-regulating wool for cooler days.",
    "merino": "Fine merino that's warm without the bulk.",
    "cashmere": "A touch of cashmere for a softer hand-feel.",
    "leather": "Genuine leather that develops character as it ages.",
    "suede": "Velvety suede — treat with a protector spray before the monsoon.",
    "silk": "A subtle sheen from the silk-blend weave.",
    "fleece": "Brushed inside for extra warmth.",
    "cotton": "Breathable cotton that's easy to care for.",
    "satin": "Fluid satin that moves beautifully.",
    "knit": "A soft, breathable knit with natural stretch.",
    "canvas": "Hard-wearing canvas built for daily use.",
}


_NOUNS = {
    "t-shirts": "tee",
    "polos": "polo",
    "casual-shirts": "shirt",
    "formal-shirts": "shirt",
    "blouses-tops": "top",
    "knitwear": "sweater",
    "hoodies-sweatshirts": "hoodie",
    "chinos": "chinos",
    "jeans": "jeans",
    "trousers": "trousers",
    "shorts": "shorts",
    "joggers": "joggers",
    "skirts": "skirt",
    "day-evening-dresses": "dress",
    "blazers": "blazer",
    "jackets": "jacket",
    "kurtas": "kurta",
    "nehru-jackets": "Nehru jacket",
    "sneakers": "sneakers",
    "loafers": "loafers",
    "formal-shoes": "shoes",
    "boots": "boots",
    "sandals": "sandals",
    "juttis": "juttis",
    "belts": "belt",
    "bags": "bag",
    "caps": "cap",
    "scarves-stoles": "scarf",
}
_SELF_NAMING_FITS = ("Heel", "Flat", "Pump", "Slip", "Wrap", "Tote", "Shopper", "Weekender")


def _noun_phrase(spec: Spec, fit: str, name: str) -> tuple[str, bool]:
    """Returns ("block heels", plural?) style phrases for use in descriptions."""
    if spec.slug == "ethnic-bottoms":
        noun = (
            "churidar"
            if "Churidar" in name
            else "palazzos"
            if "Palazzo" in name
            else "pyjama pants"
        )
    elif spec.slug == "heels-flats":
        noun = ""
    else:
        noun = _NOUNS[spec.slug]
    fit_l = "classic" if fit == "Regular" else fit.lower()
    if any(word in fit for word in _SELF_NAMING_FITS):
        phrase = fit_l + ("s" if spec.slug == "heels-flats" else f" {noun}")
    else:
        phrase = f"{fit_l} {noun}".strip()
    plural = (
        phrase.endswith(("s", "jeans"))
        and not phrase.endswith(("dress", "chinos"))
        or phrase.endswith(("chinos", "jeans", "trousers", "shorts", "joggers", "pants"))
    )
    return phrase, plural


_OPENERS = [
    "{Art} {phrase} in {material_l}, finished in {colour_l}.",
    "{Material} gives {this} {phrase} {its} easy drape, here in {colour_l}.",
    "Our {phrase}, cut from {material_l} in {colour_art} {colour_l} you'll reach for often.",
    "{Colour} {material_l}, shaped into {art_l} {phrase} that {holds} {its} line all day.",
]


def _description(
    rng: random.Random, spec: Spec, fit: str, material: str, colour: str, tags: list[str], name: str
) -> str:
    phrase, plural = _noun_phrase(spec, fit, name)
    article = "an" if phrase[0] in "aeiou" else "a"
    openers = (
        _OPENERS if spec.slot not in ("footwear", "accessory") else _OPENERS[::2] + _OPENERS[2:3]
    )
    opener = rng.choice(openers).format(
        Art="A pair of" if plural else article.capitalize(),
        art_l="a pair of" if plural else article,
        this="these" if plural else "this",
        its="their" if plural else "its",
        holds="hold" if plural else "holds",
        phrase=phrase,
        Material=material,
        material_l=material.lower(),
        Colour=colour,
        colour_l=colour.lower(),
        colour_art="an" if colour[0] in "AEIOU" else "a",
    )
    character = _CHARACTER.get(tags[0], _CHARACTER["casual"])
    note = next((v for k, v in _MATERIAL_NOTE.items() if k in material.lower()), "")
    return " ".join(part for part in (opener, character, note) if part)


def _colour_code(colour: str) -> str:
    words = re.split(r"[\s-]+", colour.upper())
    return words[0][:3] if len(words) == 1 else words[0][0] + words[-1][:2]


def _stock(rng: random.Random, sizes: list[str], online: bool, carried: bool) -> list[int]:
    if not carried:
        return [0] * len(sizes)
    out = []
    for size in sizes:
        weight = SIZE_WEIGHT.get(size, 0.8)
        if online:
            qty = int(rng.triangular(0, 30, 12) * weight)
        else:
            # About one size in six is sold out at a given store.
            qty = 0 if rng.random() < 0.17 else max(1, int(rng.triangular(1, 12, 4) * weight))
        out.append(qty)
    return out


def generate_catalogue(seed: int = DEFAULT_SEED) -> list[GenProduct]:
    rng = random.Random(seed)
    brands = {b.slug: b for b in BRANDS}
    products: list[GenProduct] = []
    used_slugs: set[str] = set()
    style_no = 0

    for spec in SPECS:
        for _ in range(spec.styles):
            style_no += 1
            brand = brands[rng.choice(spec.brands)]
            gender = _weighted(rng, spec.genders)
            material = rng.choice(spec.materials)
            fit = rng.choice(spec.fits)
            pattern = _weighted(rng, spec.patterns)
            name = _name(rng, spec, fit, material, pattern)

            # Brand focus nudges which style tags lead.
            pool = list(spec.style_tags)
            rng.shuffle(pool)
            pool.sort(key=lambda t: t not in brand.focus)
            tags = pool[: rng.randint(2, min(3, len(pool)))]
            occasions = rng.sample(spec.occasions, k=rng.randint(2, min(3, len(spec.occasions))))
            seasons = list(spec.seasons)

            base = rng.uniform(*spec.price) * TIER_MULTIPLIER[brand.tier]
            price = _retail_price(min(max(base, spec.price[0] * 0.8), spec.price[1] * 1.35))
            formality = rng.randint(*spec.formality)
            if "formal" in tags:
                formality = max(formality, min(5, spec.formality[1]))
            style_code = f"{brand.slug[:2].upper()}{spec.slug[:2].upper()}-{style_no:04d}"
            colours = rng.sample(
                spec.colours, k=min(rng.randint(*spec.colourways), len(spec.colours))
            )
            on_sale = rng.random() < 0.22
            created_days_ago = rng.randint(0, 180)
            popularity = int(rng.paretovariate(1.6) * 40)
            sizes = _sizes_for(spec, gender)

            for colour in colours:
                hex_, family = COLOURS[colour]
                secondary: list[str] = []
                if pattern in ("striped", "checked", "printed"):
                    accents = [c for c in ACCENT_COLOURS if c != colour]
                    secondary = rng.sample(accents, k=rng.randint(1, 2))
                elif spec.shape == "sneaker" and colour != "White":
                    secondary = ["White"]

                slug = _slugify(f"{brand.name} {name} {colour}")
                if slug in used_slugs:
                    slug = f"{slug}-{style_no}"
                used_slugs.add(slug)
                colour_code = _colour_code(colour)

                product = GenProduct(
                    key=len(products) + 1,
                    style_code=style_code,
                    slug=slug,
                    name=name,
                    brand_slug=brand.slug,
                    category_slug=spec.slug,
                    shape=spec.shape,
                    gender=gender,
                    colour=colour,
                    colour_hex=hex_,
                    colour_family=family,
                    secondary_colours=secondary,
                    pattern=pattern,
                    material=material,
                    fit=fit,
                    style_tags=tags,
                    occasions=occasions,
                    seasons=seasons,
                    formality=formality,
                    price=price,
                    mrp=_retail_price(price * rng.uniform(1.2, 1.5)) if on_sale else price,
                    description=_description(rng, spec, fit, material, colour, tags, name),
                    popularity=popularity + rng.randint(0, 25),
                    is_active=rng.random() > 0.02,
                    created_at=CATALOGUE_EPOCH
                    - timedelta(days=created_days_ago, minutes=len(products)),
                )
                carried = {s.code: rng.random() < s.carry_rate for s in STORES}
                stock_by_store = {
                    s.code: _stock(rng, sizes, s.is_online, carried[s.code]) for s in STORES
                }
                for i, size in enumerate(sizes):
                    size_code = size.replace("UK ", "UK").replace(" ", "")
                    product.variants.append(
                        GenVariant(
                            sku=f"{style_code}-{colour_code}-{size_code}",
                            size=size,
                            size_rank=SIZE_RANK[size],
                            stock={code: levels[i] for code, levels in stock_by_store.items()},
                        )
                    )
                products.append(product)

    _apply_demo_scenarios(products)
    return products


def _apply_demo_scenarios(products: list[GenProduct]) -> None:
    """Pin a few stock situations the README demo script relies on."""
    # "Do you have these beige chinos in size M?" -> sold out in Pune, available elsewhere.
    beige_chinos = next(
        (
            p
            for p in products
            if p.category_slug == "chinos" and p.colour == "Beige" and p.is_active
        ),
        None,
    )
    if beige_chinos:
        for v in beige_chinos.variants:
            if v.size == "M":
                v.stock["PUN"] = 0
                v.stock["BOM"] = max(v.stock["BOM"], 3)
                v.stock["WEB"] = max(v.stock["WEB"], 8)
