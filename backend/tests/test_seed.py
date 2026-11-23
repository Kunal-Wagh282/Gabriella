"""The generated catalogue is the ground truth Gabriella is graded against, so check it hard."""

from collections import Counter

import pytest

from seed.generator import generate_catalogue
from seed.render import SHAPES, H, W, render_flatlay
from seed.taxonomy import COLOURS, SPECS, STORES


@pytest.fixture(scope="module")
def products():
    return generate_catalogue()


def test_catalogue_size_and_determinism(products):
    assert 300 <= len(products) <= 600
    again = generate_catalogue()
    assert [(p.slug, p.price, [v.stock for v in p.variants]) for p in products] == [
        (p.slug, p.price, [v.stock for v in p.variants]) for p in again
    ]


def test_identifiers_are_unique(products):
    slugs = [p.slug for p in products]
    skus = [v.sku for p in products for v in p.variants]
    assert len(slugs) == len(set(slugs))
    assert len(skus) == len(set(skus))


def test_every_category_gender_and_store_is_represented(products):
    by_category = Counter(p.category_slug for p in products)
    assert set(by_category) == {s.slug for s in SPECS}
    assert {p.gender for p in products} == {"men", "women", "unisex"}
    stocked_codes = {code for p in products for v in p.variants for code, q in v.stock.items() if q}
    assert stocked_codes == {s.code for s in STORES}


def test_attributes_are_consistent(products):
    for p in products:
        assert COLOURS[p.colour] == (p.colour_hex, p.colour_family)
        assert all(c in COLOURS for c in p.secondary_colours)
        assert 0 < p.price <= p.mrp
        assert 1 <= p.formality <= 5
        assert p.style_tags and p.occasions and p.seasons
        assert p.variants and all(q >= 0 for v in p.variants for q in v.stock.values())
        assert p.description.endswith(".")
        assert "  " not in p.name


def test_inventory_has_gaps_and_depth(products):
    """Recommendations need realistic sell-outs to exercise the fallback paths."""
    levels = [
        q for p in products for v in p.variants for code, q in v.stock.items() if code != "WEB"
    ]
    sold_out = sum(1 for q in levels if q == 0) / len(levels)
    assert 0.15 < sold_out < 0.6


def test_demo_scenario_beige_chinos_sold_out_in_pune(products):
    chinos = next(
        p for p in products if p.category_slug == "chinos" and p.colour == "Beige" and p.is_active
    )
    size_m = next(v for v in chinos.variants if v.size == "M")
    assert size_m.stock["PUN"] == 0
    assert size_m.stock["BOM"] > 0


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_every_shape_renders(shape):
    img = render_flatlay(shape, "#1F2A44", pattern="striped", secondary_hex=["#F7F6F2"], seed=1)
    assert img.size == (W, H)
    # The garment covers a meaningful share of the canvas, i.e. it isn't blank.
    grey = img.convert("L")
    background = grey.getpixel((5, 5))
    histogram = grey.histogram()
    covered = sum(n for level, n in enumerate(histogram) if abs(level - background) > 25)
    assert covered / (W * H) > 0.03
