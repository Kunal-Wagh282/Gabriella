"""Understand a shopper's photo of their own garment, with no paid vision API.

* Garment type: CLIP zero-shot against the catalogue's own leaf categories, blended with a
  vote from the visually nearest catalogue photos (k-NN), which corrects most zero-shot slips.
* Pattern: CLIP zero-shot (solid / striped / checked / printed).
* Colour: the dominant non-background colour, snapped to the nearest catalogue colour.

The result is a style hint, not an identification: confidence is reported and shown to the shopper.
"""

import io
import math
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from anyio import to_thread
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Category, Product, ProductEmbedding
from app.ml.embeddings import get_embedder
from app.retrieval.documents import singular

MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE = 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
UPLOAD_TTL = timedelta(hours=24)
Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs

PATTERN_PROMPTS = {
    "solid": "a photo of a plain solid-colour garment",
    "striped": "a photo of a striped garment",
    "checked": "a photo of a checked plaid garment",
    "printed": "a photo of a garment with a floral or graphic print",
}


class InvalidImage(AppError):
    status_code = 415
    code = "invalid_image"


@dataclass
class GarmentAnalysis:
    category: str
    category_name: str
    slot: str
    confidence: float
    colour: str
    colour_hex: str
    colour_family: str
    pattern: str
    formality: int
    label: str  # "navy shirt"

    def as_dict(self) -> dict:
        return asdict(self)


def load_image(data: bytes) -> Image.Image:
    """Validate and normalise an upload. Re-encoding later strips EXIF/GPS metadata."""
    if len(data) > MAX_BYTES:
        raise InvalidImage("Images must be 8 MB or smaller")
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = probe.format
        probe.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidImage("That file isn't a readable image") from exc
    if fmt not in ALLOWED_FORMATS:
        raise InvalidImage("Please upload a JPEG, PNG or WebP photo")
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.info.clear()  # drop EXIF/GPS and any other embedded metadata
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    return image


def save_upload(image: Image.Image) -> tuple[str, str]:
    """Store under a random name. Returns (file name, public URL)."""
    settings = get_settings()
    folder = settings.media_root / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.webp"
    image.save(folder / name, "WEBP", quality=85)  # fresh file: no metadata carried over
    return name, f"{settings.media_url}/uploads/{name}"


def upload_expiry() -> datetime:
    return datetime.now(UTC) + UPLOAD_TTL


def upload_path(name: str) -> Path:
    return get_settings().media_root / "uploads" / name


# ------------------------------------------------------------------ colour


def _redmean(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """Cheap perceptual colour distance."""
    r = (a[0] + b[0]) / 2
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return math.sqrt((2 + r / 256) * dr * dr + 4 * dg * dg + (2 + (255 - r) / 256) * db * db)


def dominant_colour(image: Image.Image) -> tuple[int, int, int]:
    """Most common colour that isn't the background (estimated from the border)."""
    small = image.resize((64, 64))
    px = list(small.get_flattened_data())
    border = (
        [px[i] for i in range(64)]
        + [px[-64 + i] for i in range(64)]
        + [px[i * 64] for i in range(64)]
    )
    bg = tuple(sorted(c[k] for c in border)[len(border) // 2] for k in range(3))
    garment = [p for p in px if _redmean(p, bg) > 60]  # type: ignore[arg-type]
    pixels = garment if len(garment) > len(px) * 0.08 else px
    sample = Image.new("RGB", (len(pixels), 1))
    sample.putdata(pixels)
    palette_img = sample.quantize(colors=4, method=Image.Quantize.MEDIANCUT)
    counts = sorted(palette_img.getcolors() or [], reverse=True)
    palette = palette_img.getpalette() or []
    idx = counts[0][1]
    return (palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2])


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


# ------------------------------------------------------------------ CLIP zero-shot


def _softmax(scores: list[float], scale: float = 100.0) -> list[float]:
    peak = max(scores)
    exps = [math.exp((s - peak) * scale) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


@lru_cache(maxsize=8)
def _prompt_vectors(prompts: tuple[str, ...]) -> list[list[float]]:
    return get_embedder().embed_texts(list(prompts))


def _zero_shot(image_vec: list[float], prompts: tuple[str, ...]) -> list[float]:
    vectors = _prompt_vectors(prompts)
    return _softmax([sum(a * b for a, b in zip(image_vec, v, strict=True)) for v in vectors])


KNN_NEIGHBOURS = 12
KNN_WEIGHT = 0.5  # share of the category decision given to the nearest-photo vote


async def _neighbour_vote(
    session: AsyncSession, image_vec: list[float], exclude_product_id: int | None
) -> dict[int, float]:
    """Category id -> share of similarity among the nearest catalogue photos."""
    distance = ProductEmbedding.image_embedding.cosine_distance(image_vec)
    query = (
        select(Product.category_id, distance)
        .join(Product, Product.id == ProductEmbedding.product_id)
        .where(ProductEmbedding.image_embedding.is_not(None))
        .order_by(distance)
        .limit(KNN_NEIGHBOURS)
    )
    if exclude_product_id is not None:
        query = query.where(ProductEmbedding.product_id != exclude_product_id)
    votes: dict[int, float] = {}
    for category_id, dist in (await session.execute(query)).all():
        votes[category_id] = votes.get(category_id, 0.0) + max(0.0, 1.0 - float(dist))
    total = sum(votes.values())
    return {k: v / total for k, v in votes.items()} if total else {}


async def analyse(
    session: AsyncSession, image: Image.Image, *, exclude_product_id: int | None = None
) -> tuple[GarmentAnalysis, list[float]]:
    """Returns the analysis and the image's CLIP vector (for visual similarity search).
    `exclude_product_id` keeps a catalogue photo from voting for itself (used by the evals)."""
    categories = (
        await session.scalars(
            select(Category).where(Category.slot.is_not(None)).order_by(Category.position)
        )
    ).all()
    colours = (
        await session.execute(
            select(Product.colour, Product.colour_hex, Product.colour_family).distinct()
        )
    ).all()
    formality = dict(
        (
            await session.execute(
                select(Product.category_id, func.avg(Product.formality)).group_by(
                    Product.category_id
                )
            )
        ).all()
    )

    embedder = get_embedder()
    image_vec = (await to_thread.run_sync(embedder.embed_images, [image]))[0]
    cat_prompts = tuple(f"a photo of a {singular(c.name)}" for c in categories)
    zero_shot = await to_thread.run_sync(_zero_shot, image_vec, cat_prompts)
    votes = await _neighbour_vote(session, image_vec, exclude_product_id)
    weight = KNN_WEIGHT if votes else 0.0
    cat_probs = [
        (1 - weight) * p + weight * votes.get(c.id, 0.0)
        for p, c in zip(zero_shot, categories, strict=True)
    ]
    best = max(range(len(categories)), key=lambda i: cat_probs[i])
    category = categories[best]
    pat_probs = await to_thread.run_sync(_zero_shot, image_vec, tuple(PATTERN_PROMPTS.values()))
    pattern = list(PATTERN_PROMPTS)[max(range(len(pat_probs)), key=lambda i: pat_probs[i])]

    rgb = await to_thread.run_sync(dominant_colour, image)
    name, hex_, family = min(colours, key=lambda c: _redmean(rgb, _hex_to_rgb(c[1])))
    noun = singular(category.name).split(" and ")[0]
    return (
        GarmentAnalysis(
            category=category.slug,
            category_name=category.name,
            slot=category.slot or "top",
            confidence=round(cat_probs[best], 2),
            colour=name,
            colour_hex=hex_,
            colour_family=family,
            pattern=pattern,
            formality=round(float(formality.get(category.id, 3))),
            label=f"{name.lower()} {'' if pattern == 'solid' else pattern + ' '}{noun}".strip(),
        ),
        image_vec,
    )
