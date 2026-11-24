"""Evaluation cases. Each chat case is one conversation; checks apply to the final answer.

Universal checks run on every answer (grounding, stock, budget, size). The `expect` fields
add case-specific checks. Product focus and photos refer to catalogue items by query, so the
suite works on any seed.
"""

from dataclasses import dataclass, field


@dataclass
class ChatCase:
    id: str
    group: str  # what capability it exercises
    turns: list[str]
    store: str = "PUN"
    signed_in: bool = False  # as the seeded demo shopper (has purchase history)
    personalisation: bool = True
    focus_query: str | None = None  # style this catalogue product
    photo_query: str | None = None  # upload this catalogue product's image as "my own garment"
    # Expectations on the final answer
    kind: str | None = None  # outfit | picks | alternatives | question | none
    budget: int | None = None
    apparel_size: str | None = None
    footwear_size: str | None = None
    slots_include: set[str] = field(default_factory=set)
    slots_exclude: set[str] = field(default_factory=set)
    categories_any: set[str] = field(default_factory=set)  # every item in one of these
    colour_family_any: set[str] = field(default_factory=set)  # at least one item
    gender: str | None = None
    min_formality: float | None = None  # mean formality of apparel items
    max_formality: float | None = None
    message_contains: list[str] = field(default_factory=list)  # "a|b" = either phrase
    title_is: str | None = None
    formality_drops: bool = False  # last outfit less formal than the one before
    profile_colour_share: float | None = None  # share of items in the profile's colour families


ETHNIC = {
    "kurtas",
    "ethnic-bottoms",
    "nehru-jackets",
    "juttis",
    "day-evening-dresses",
    "loafers",
    "formal-shoes",
    "heels-flats",
    "belts",
    "bags",
    "scarves-stoles",
    "skirts",
    "blouses-tops",
}

CHAT_CASES: list[ChatCase] = [
    # --- outfits, budgets, sizes, occasions
    ChatCase(
        "dinner-budget",
        "outfit",
        ["Casual dinner outfit for men under ₹6,000, I wear M and UK 9"],
        kind="outfit",
        budget=6000,
        apparel_size="M",
        footwear_size="UK 9",
        slots_include={"top", "bottom", "footwear"},
        gender="men",
    ),
    ChatCase(
        "office-men",
        "occasion",
        ["Office outfit for men, size L and UK 10"],
        kind="outfit",
        apparel_size="L",
        footwear_size="UK 10",
        min_formality=3.0,
        gender="men",
    ),
    ChatCase(
        "sangeet-women",
        "occasion",
        ["Sangeet outfit for women, size S, budget 12000"],
        kind="outfit",
        budget=12000,
        apparel_size="S",
        categories_any=ETHNIC,
        gender="women",
    ),
    ChatCase(
        "party-women",
        "occasion",
        ["Party look for women in M under 9000"],
        kind="outfit",
        budget=9000,
        apparel_size="M",
        gender="women",
    ),
    ChatCase(
        "travel-men",
        "occasion",
        ["Comfortable travel outfit for men, size XL"],
        kind="outfit",
        apparel_size="XL",
        max_formality=3.0,
        gender="men",
    ),
    ChatCase(
        "navy-office",
        "outfit",
        ["Navy outfit for men for the office, M and UK 9"],
        kind="outfit",
        apparel_size="M",
        footwear_size="UK 9",
        colour_family_any={"blue"},
    ),
    ChatCase(
        "budget-impossible",
        "no-result",
        ["Formal outfit for men under ₹2,000"],
        kind="none",
        message_contains=["₹"],
    ),
    ChatCase("ask-gender", "clarify", ["Outfit for a dinner"], kind="question"),
    # --- refinement across turns
    ChatCase(
        "less-formal",
        "refine",
        ["Office outfit for men, M and UK 9", "Make it less formal"],
        kind="outfit",
        apparel_size="M",
        footwear_size="UK 9",
        formality_drops=True,
    ),
    ChatCase(
        "refine-budget",
        "refine",
        ["Office outfit for men, M and UK 9", "Keep it under 7000"],
        kind="outfit",
        budget=7000,
        apparel_size="M",
    ),
    ChatCase(
        "start-fresh",
        "refine",
        ["Office outfit for men, size M", "start fresh"],
        kind="question",
        message_contains=["Fresh start"],
    ),
    # --- product discovery and stock
    ChatCase(
        "white-sneakers",
        "search",
        ["white sneakers in UK 9"],
        kind="picks",
        footwear_size="UK 9",
        categories_any={"sneakers"},
    ),
    ChatCase(
        "black-dress-sale",
        "search",
        ["black dresses on sale"],
        categories_any={"day-evening-dresses"},
        colour_family_any={"black"},
    ),
    ChatCase(
        "kurta-budget",
        "search",
        ["kurta for women under 2500"],
        kind="picks",
        budget=2500,
        categories_any={"kurtas"},
    ),
    ChatCase(
        "linen-shirt-L",
        "search",
        ["linen shirts for men in L"],
        kind="picks",
        apparel_size="L",
        categories_any={"casual-shirts", "formal-shirts"},
    ),
    ChatCase(
        "mumbai-stock",
        "stock",
        ["white sneakers in UK 9"],
        store="BOM",
        categories_any={"sneakers"},
        footwear_size="UK 9",
    ),
    ChatCase(
        "similar-chinos-M",
        "similar",
        ["Do you have something similar in M?"],
        focus_query="beige chinos",
        kind="alternatives",
        apparel_size="M",
        slots_include={"bottom"},
    ),
    ChatCase(
        "availability-sold-out",
        "stock",
        ["Do you have these in M?"],
        focus_query="field day relaxed garment-dyed cotton chinos beige",
        message_contains=["sold out|out of stock|not in stock"],
    ),
    ChatCase(
        "style-product",
        "outfit",
        ["What goes with this for the office? Menswear, M and UK 9"],
        focus_query="navy formal shirt men",
        kind="outfit",
        slots_exclude=set(),
    ),
    # --- graceful handling
    ChatCase("impossible-filters", "no-result", ["gold sneakers in UK 3"], kind="none"),
    ChatCase(
        "off-topic",
        "no-result",
        ["What's the capital of France?"],
        kind="none",
        message_contains=["cloth"],
    ),
    # --- personalisation
    ChatCase(
        "personal-picks",
        "personalisation",
        ["Suggest something new based on what I bought before"],
        signed_in=True,
        kind="picks",
        title_is="Picked for you",
        profile_colour_share=0.5,
    ),
    ChatCase(
        "personal-off",
        "personalisation",
        ["Suggest something new based on what I bought before"],
        signed_in=True,
        personalisation=False,
    ),
    # --- photos of the shopper's own garment
    ChatCase(
        "photo-shirt-outfit",
        "image",
        ["What trousers and shoes go with this? Menswear, M and UK 9"],
        photo_query="navy casual shirt men",
        kind="outfit",
        slots_include={"bottom", "footwear"},
        slots_exclude={"top"},
    ),
    ChatCase(
        "photo-sneaker-similar",
        "image",
        ["Show me similar ones"],
        photo_query="white leather sneakers",
        kind="alternatives",
        categories_any={"sneakers"},
    ),
    ChatCase(
        "photo-dress-shoes",
        "image",
        ["What shoes go with this? Womenswear, UK 5"],
        photo_query="black dress women",
        kind="outfit",
        slots_include={"footwear"},
        slots_exclude={"onepiece"},
    ),
]


@dataclass
class RetrievalCase:
    query: str
    categories: set[str]
    colour_families: set[str] = field(default_factory=set)


RETRIEVAL_CASES: list[RetrievalCase] = [
    RetrievalCase("beige chinos", {"chinos"}, {"neutral"}),
    RetrievalCase("denim jacket", {"jackets"}),
    RetrievalCase("office shoes for men", {"formal-shoes", "loafers"}),
    RetrievalCase(
        "cosy winter layer",
        {"knitwear", "hoodies-sweatshirts", "jackets", "scarves-stoles", "blazers"},
    ),
    RetrievalCase(
        "light summer shirt", {"casual-shirts", "formal-shirts", "t-shirts", "blouses-tops"}
    ),
    RetrievalCase("black party dress", {"day-evening-dresses"}, {"black"}),
    RetrievalCase("outfit for a sangeet", {"kurtas", "ethnic-bottoms", "nehru-jackets", "juttis"}),
    RetrievalCase("white sneakers", {"sneakers"}, {"white"}),
    RetrievalCase("formal trousers", {"trousers"}),
    RetrievalCase("leather belt", {"belts"}),
    RetrievalCase(
        "something to wear to a beach holiday",
        {"shorts", "t-shirts", "sandals", "casual-shirts", "caps", "bags"},
    ),
    RetrievalCase("smart office blazer", {"blazers"}),
    RetrievalCase(
        "ethnic footwear for a wedding", {"juttis", "loafers", "formal-shoes", "heels-flats"}
    ),
    RetrievalCase("warm hoodie", {"hoodies-sweatshirts"}),
]
