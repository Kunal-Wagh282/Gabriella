"""Text representations of products for embedding and full-text search."""

from app.db.models import Product

_GENDER = {"men": "men", "women": "women", "unisex": "everyone"}
_IRREGULAR = {
    "dresses": "dress",
    "shoes": "shoes",
    "jeans": "jeans",
    "chinos": "chinos",
    "trousers": "trousers",
    "shorts": "shorts",
    "joggers": "joggers",
}


def singular(category_name: str) -> str:
    """'Casual Shirts' -> 'casual shirt'; leaves inherently plural garments alone."""
    words = category_name.lower().replace("&", "and").split()
    last = words[-1]
    words[-1] = _IRREGULAR.get(
        last, last[:-1] if last.endswith("s") and not last.endswith("ss") else last
    )
    return " ".join(words)


def product_document(product: Product) -> str:
    """A caption-style description. Kept short: CLIP's text encoder reads at most 77 tokens."""
    pattern = "" if product.pattern == "solid" else f"{product.pattern} "
    tags = ", ".join(t.replace("-", " ") for t in product.style_tags[:3])
    return (
        f"a photo of a {product.colour.lower()} {pattern}{product.material.lower()} "
        f"{singular(product.category.name)} for {_GENDER[product.gender]}, "
        f"{product.fit.lower()} fit, {tags} style"
    )
