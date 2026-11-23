import pytest

from app.retrieval.query_parser import parse_query
from app.retrieval.search import semantic_text, tsquery_text
from app.retrieval.vocabulary import CATEGORY_PHRASES
from seed.taxonomy import GROUPS, SPECS


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "beige chinos under ₹3k in M",
            dict(categories=["chinos"], colours=["beige"], sizes=["M"], max_price=3000),
        ),
        (
            "casual dinner under 5,000",
            dict(max_price=5000, occasions=["dinner"], styles=["casual"]),
        ),
        (
            "Navy linen shirts for men size L",
            dict(colours=["navy"], sizes=["L"], genders=["men", "unisex"]),
        ),
        ("white sneakers uk 9", dict(categories=["sneakers"], colours=["white"], sizes=["UK 9"])),
        (
            "kurta for women between 2000 and 4000",
            dict(categories=["kurtas"], min_price=2000, max_price=4000),
        ),
        ("black dresses on sale", dict(categories=["day-evening-dresses"], on_sale=True)),
        ("formal shirt for the office", dict(categories=["formal-shirts"], occasions=["office"])),
        ("trousers over rs 2500", dict(categories=["trousers"], min_price=2500)),
        ("budget 4k loafers", dict(categories=["loafers"], max_price=4000)),
        ("denim jacket", dict(categories=["jackets"])),  # denim is a fabric here
        ("denim", dict(categories=["jeans"])),
        ("shoes in medium blue", dict(sizes=[], colours=["blue"], categories=["footwear"])),
        ("a shirt in medium", dict(sizes=["M"])),
        ("tees 2-3 pack", dict(min_price=None, max_price=None)),  # not a price range
        ("wedding outfit", dict(occasions=["wedding", "festive"], categories=[])),
    ],
)
def test_parse_query(query, expected):
    parsed = parse_query(query)
    for field, value in expected.items():
        actual = getattr(parsed, field)
        if field == "categories" and value:
            assert set(value) <= set(actual), (field, actual)
        else:
            assert actual == value, (field, actual)


def test_residual_text_drops_consumed_phrases_but_keeps_descriptors():
    parsed = parse_query("navy linen shirt under 2000 in L for men")
    assert parsed.text == "navy linen shirt"
    assert {i.kind for i in parsed.interpretations} >= {
        "price",
        "size",
        "gender",
        "colour",
        "category",
    }


def test_every_vocabulary_category_exists_in_the_taxonomy():
    slugs = {s.slug for s in SPECS} | {g for g, _ in GROUPS}
    referenced = {slug for slugs_ in CATEGORY_PHRASES.values() for slug in slugs_}
    assert referenced <= slugs, referenced - slugs


def test_lexical_query_removes_filler_and_expands_synonyms():
    q = tsquery_text("something to wear to the office in pants")
    assert q is not None
    terms = set(q.split(" | "))
    assert {"office", "formal", "pants", "trousers"} <= terms
    assert not terms & {"something", "wear"}
    assert tsquery_text("something to wear") is None
    assert tsquery_text("tux", expand=False) == "tux"


def test_semantic_text_translates_occasions():
    assert semantic_text("shoes for the office") == "shoes office formal"
