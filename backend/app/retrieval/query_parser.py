"""Deterministic query understanding for the search box.

Turns "beige chinos under ₹3k in M for men" into structured constraints:

* hard filters: categories, colours, genders, sizes, price range, on-sale
* soft signals: occasions and styles (boost ranking; products carry only a few occasion tags,
  so filtering on them would wrongly hide good matches)
* residual free text for lexical + semantic ranking

Gabriella's LLM extracts constraints itself from Phase 3; this parser powers the search bar
and the no-LLM fallback.
"""

import re
from dataclasses import dataclass, field

from app.retrieval.vocabulary import (
    CATEGORY_PHRASES,
    COLOUR_PHRASES,
    GENDER_PHRASES,
    MATERIAL_CATEGORY_PHRASES,
    OCCASION_PHRASES,
    SIZE_WORDS,
    STYLE_PHRASES,
)


@dataclass
class Interpretation:
    kind: str  # category | colour | gender | size | price | occasion | style | sale
    value: str
    label: str
    phrase: str


@dataclass
class ParsedQuery:
    raw: str
    text: str  # residual free text for ranking
    categories: list[str] = field(default_factory=list)
    colours: list[str] = field(default_factory=list)
    genders: list[str] = field(default_factory=list)
    sizes: list[str] = field(default_factory=list)
    min_price: int | None = None
    max_price: int | None = None
    on_sale: bool = False
    occasions: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)
    interpretations: list[Interpretation] = field(default_factory=list)


_AMOUNT = r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?"
_MAX_RE = re.compile(
    rf"\b(?:under|below|less than|upto|up to|within|max(?:imum)?|cheaper than|not more than|<)\s*{_AMOUNT}",
    re.I,
)
_MIN_RE = re.compile(rf"\b(?:over|above|more than|from|min(?:imum)?|at least|>)\s*{_AMOUNT}", re.I)
_RANGE_RE = re.compile(rf"(?:between\s*)?{_AMOUNT}\s*(?:-|–|to|and)\s*{_AMOUNT}", re.I)
_BUDGET_RE = re.compile(rf"\bbudget(?: of| is)?\s*{_AMOUNT}", re.I)
_UK_SIZE_RE = re.compile(r"\b(?:uk|size)\s*(\d{1,2})\b", re.I)
_ALPHA_SIZE_RE = re.compile(
    r"\b(?:in\s+(?:a\s+)?size|size|(?:i\s+)?wear(?:\s+a)?|i\s*(?:'m|am)(?:\s+an?)?|in(?:\s+a)?)\s+(extra small|extra large|xxl|2xl|xl|xs|small|medium|large|s|m|l)\b",
    re.I,
)
_SALE_RE = re.compile(r"\b(?:on sale|sale|discount(?:ed)?|on offer|offers?)\b", re.I)


def _amount(number: str, k: str | None) -> int:
    value = float(number.replace(",", ""))
    return int(value * 1000 if k else value)


def _uniq(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "shes", "ches", "xes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us")) and len(word) > 3:
        return word[:-1]
    return word


def _phrase_pattern(phrases: list[str]) -> re.Pattern[str]:
    alternatives = sorted(phrases, key=len, reverse=True)
    return re.compile(
        r"(?<![\w-])(" + "|".join(re.escape(p) for p in alternatives) + r")(?![\w-])", re.I
    )


_CATEGORY_RE = _phrase_pattern(list(CATEGORY_PHRASES))
_COLOUR_RE = _phrase_pattern(list(COLOUR_PHRASES))
_GENDER_RE = _phrase_pattern(list(GENDER_PHRASES))
_OCCASION_RE = _phrase_pattern(list(OCCASION_PHRASES))
_STYLE_RE = _phrase_pattern(list(STYLE_PHRASES))


_UNCOUNTABLE = {"denim", "knitwear", "footwear", "ethnic wear", "accessories"}


def _category_label(phrase: str) -> str:
    """'chino' -> 'Chinos', 'dress' -> 'Dresses', 'footwear' -> 'Footwear'."""
    phrase = phrase.strip().lower()
    if phrase in _UNCOUNTABLE or (phrase.endswith("s") and not phrase.endswith("ss")):
        return phrase.title()
    suffix = "es" if phrase.endswith(("ss", "sh", "ch", "x")) else "s"
    return (phrase + suffix).title()


def _normalise_plurals(text: str) -> str:
    """Singularise words so 'chinos', 'shirts', 'dresses' hit the singular vocabulary."""
    return re.sub(r"[a-z]+", lambda m: _singular(m.group(0)), text)


def parse_query(raw: str) -> ParsedQuery:
    text = " ".join(raw.strip().split())
    parsed = ParsedQuery(raw=raw, text="")
    work = text.lower()

    def consume(span: tuple[int, int]) -> None:
        nonlocal work
        work = work[: span[0]] + " " * (span[1] - span[0]) + work[span[1] :]

    # Price
    if m := _RANGE_RE.search(work):
        lo, hi = _amount(m.group(1), m.group(2)), _amount(m.group(3), m.group(4))
        if lo < hi and hi >= 100:  # skip things like "2-3" that aren't prices
            parsed.min_price, parsed.max_price = lo, hi
            parsed.interpretations.append(
                Interpretation("price", f"{lo}-{hi}", f"₹{lo:,} – ₹{hi:,}", m.group(0))
            )
            consume(m.span())
    for regex, attr in ((_MAX_RE, "max_price"), (_BUDGET_RE, "max_price"), (_MIN_RE, "min_price")):
        if getattr(parsed, attr) is None and (m := regex.search(work)):
            value = _amount(m.group(1), m.group(2))
            if value >= 100:
                setattr(parsed, attr, value)
                label = f"Under ₹{value:,}" if attr == "max_price" else f"Over ₹{value:,}"
                parsed.interpretations.append(
                    Interpretation("price", str(value), label, m.group(0))
                )
                consume(m.span())

    # Sizes
    for m in list(_UK_SIZE_RE.finditer(work)):
        size = f"UK {int(m.group(1))}"
        parsed.sizes.append(size)
        parsed.interpretations.append(Interpretation("size", size, f"Size {size}", m.group(0)))
        consume(m.span())
    for m in list(_ALPHA_SIZE_RE.finditer(work)):
        word = m.group(1).lower()
        following = work[m.end() :].split()
        # "in medium blue" is a colour, not a size, unless the shopper said "size".
        if (
            len(word) > 3
            and "size" not in m.group(0).lower()
            and following
            and any(
                f"{word} {following[0]}".startswith(c) or following[0] in c.split()
                for c in COLOUR_PHRASES
            )
        ):
            continue
        size = SIZE_WORDS[word]
        parsed.sizes.append(size)
        parsed.interpretations.append(Interpretation("size", size, f"Size {size}", m.group(0)))
        consume(m.span())

    if m := _SALE_RE.search(work):
        parsed.on_sale = True
        parsed.interpretations.append(Interpretation("sale", "true", "On sale", m.group(0)))
        consume(m.span())

    for m in list(_GENDER_RE.finditer(work)):
        parsed.genders += GENDER_PHRASES[m.group(1).lower()]
        label = {"men": "Men", "women": "Women"}.get(
            GENDER_PHRASES[m.group(1).lower()][0], "Unisex"
        )
        parsed.interpretations.append(Interpretation("gender", label.lower(), label, m.group(0)))
        consume(m.span())

    # Colour, occasion and style words also stay in the free text: they help ranking.
    keep = work
    for m in _COLOUR_RE.finditer(keep):
        colour = COLOUR_PHRASES[m.group(1).lower()]
        if colour not in parsed.colours:
            parsed.colours.append(colour)
            parsed.interpretations.append(
                Interpretation("colour", colour, colour.title(), m.group(0))
            )
    singular = _normalise_plurals(keep)
    category_matches = list(_CATEGORY_RE.finditer(singular))
    if any(m.group(1).lower() not in MATERIAL_CATEGORY_PHRASES for m in category_matches):
        category_matches = [
            m for m in category_matches if m.group(1).lower() not in MATERIAL_CATEGORY_PHRASES
        ]
    for m in category_matches:
        cats = CATEGORY_PHRASES[m.group(1).lower()]
        new = [c for c in cats if c not in parsed.categories]
        if new:
            parsed.categories += new
            parsed.interpretations.append(
                Interpretation(
                    "category", ",".join(cats), _category_label(m.group(1)), m.group(0).strip()
                )
            )
    for m in _OCCASION_RE.finditer(keep):
        for occ in OCCASION_PHRASES[m.group(1).lower()]:
            if occ not in parsed.occasions:
                parsed.occasions.append(occ)
        parsed.interpretations.append(
            Interpretation("occasion", m.group(1).lower(), m.group(1).title(), m.group(0))
        )
    for m in _STYLE_RE.finditer(keep):
        new = [s for s in STYLE_PHRASES[m.group(1).lower()] if s not in parsed.styles]
        if new:
            parsed.styles += new
            parsed.interpretations.append(
                Interpretation("style", new[0], m.group(1).title(), m.group(0))
            )

    parsed.genders = _uniq(parsed.genders)
    parsed.sizes = _uniq(parsed.sizes)
    # "shirt" and "formal shirt" together: the specific phrase already covers it.
    parsed.text = re.sub(r"\s+", " ", re.sub(r"[^\w\s'-]", " ", work)).strip()
    return parsed
