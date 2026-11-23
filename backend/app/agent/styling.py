"""Deterministic styling rules: colour harmony, formality and occasion fit.

Used by the no-LLM fallback to compose outfits, and to write short, factual reasons.
Kept deliberately simple and explainable: a neutral base, at most one or two accent
colour families, and pieces within one step of each other on formality.
"""

NEUTRAL_FAMILIES = {"black", "white", "neutral", "grey", "brown"}
# Accent families that sit well together beyond the neutrals.
ACCENT_PAIRS = {
    frozenset({"blue", "brown"}),
    frozenset({"blue", "neutral"}),
    frozenset({"green", "neutral"}),
    frozenset({"blue", "green"}),
    frozenset({"red", "blue"}),
    frozenset({"orange", "blue"}),
    frozenset({"pink", "grey"}),
    frozenset({"yellow", "blue"}),
    frozenset({"purple", "grey"}),
    frozenset({"green", "brown"}),
    frozenset({"orange", "green"}),
    frozenset({"metallic", "red"}),
}
OCCASION_FORMALITY = {
    "office": 4,
    "wedding": 4,
    "festive": 4,
    "dinner": 3,
    "date": 3,
    "party": 3,
    "casual": 2,
    "weekend": 2,
    "travel": 2,
}
FORMALITY_TARGET = {"relaxed": 2, "smart": 3, "formal": 4}


def colour_score(family: str, others: list[str]) -> float:
    """0..1: how well a colour family sits with the families already in the outfit."""
    if not others:
        return 1.0
    score = 1.0
    accents = [f for f in others if f not in NEUTRAL_FAMILIES]
    if family in NEUTRAL_FAMILIES:
        return 1.0 if len([f for f in others if f == family]) < 2 else 0.7
    for other in accents:
        if other == family:
            score -= 0.35  # same accent twice reads as matchy
        elif frozenset({family, other}) not in ACCENT_PAIRS:
            score -= 0.25
    if len(set(accents) | {family}) > 2:
        score -= 0.3
    return max(0.0, score)


def pairing_reason(
    colour: str, family: str, anchor_colour: str | None, anchor_family: str | None
) -> str | None:
    if not anchor_colour or not anchor_family:
        return None
    if family in NEUTRAL_FAMILIES and anchor_family in NEUTRAL_FAMILIES:
        return f"{colour} and {anchor_colour.lower()} keep the palette calm and easy"
    if family in NEUTRAL_FAMILIES:
        return f"{colour} grounds the {anchor_colour.lower()} without competing with it"
    if anchor_family in NEUTRAL_FAMILIES:
        return f"{colour} adds colour against the {anchor_colour.lower()}"
    if frozenset({family, anchor_family}) in ACCENT_PAIRS:
        return f"{colour} and {anchor_colour.lower()} are a classic pairing"
    return None


def target_formality(occasion: str | None, formality: str | None, adjust: int = 0) -> int:
    base = FORMALITY_TARGET.get(formality or "", OCCASION_FORMALITY.get(occasion or "", 3))
    return max(1, min(5, base + adjust))


def formality_word(level: int) -> str:
    return {1: "relaxed", 2: "casual", 3: "smart-casual", 4: "smart", 5: "formal"}[level]
