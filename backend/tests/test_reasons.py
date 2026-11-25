"""Reasons shown under product cards must describe that card's product."""

from types import SimpleNamespace

import pytest

from app.agent.validator import factual_reason, reason_fits


def _product(name: str, category: str, slug: str):
    return SimpleNamespace(
        name=name,
        category=SimpleNamespace(name=category, slug=slug),
        colour="Tan",
        material="Suede",
        fit="Regular",
    )


LOAFERS = _product("Tassel Loafers", "Loafers", "loafers")
TEE = _product("Oversized Slub Cotton Tee", "T-Shirts", "t-shirts")
CHINOS = _product("Relaxed Stretch Cotton Twill Chinos", "Chinos", "chinos")


@pytest.mark.parametrize(
    ("reason", "product"),
    [
        ("Tan loafers keep it polished", LOAFERS),
        ("Smart shoes that suit the occasion", LOAFERS),  # generic noun, allowed by synonym
        ("Charcoal tee adds a relaxed vibe and pairs with dark chinos", TEE),  # others later: fine
        ("A classic t-shirt", TEE),
        ("Black chinos stay relaxed yet polished", CHINOS),
        ("Comfortable trousers for a long day", CHINOS),
        ("Navy grounds the charcoal without competing with it", CHINOS),  # no garment noun
        ("", TEE),
    ],
)
def test_reasons_that_describe_the_product_are_kept(reason, product):
    assert reason_fits(reason, product)


@pytest.mark.parametrize(
    ("reason", "product"),
    [
        ("White leather court sneakers keep the vibe relaxed", LOAFERS),
        ("A crisp shirt for the office", TEE),
        ("The belt ties the look together", CHINOS),
    ],
)
def test_reasons_written_for_another_item_are_caught(reason, product):
    assert not reason_fits(reason, product)


def test_factual_replacement_names_real_attributes():
    assert factual_reason(LOAFERS) == "Tan suede, regular fit"
